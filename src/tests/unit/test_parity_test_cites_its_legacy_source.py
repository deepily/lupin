"""
A parity test names the legacy `file:line` it mirrors — build plan §6 item 19,
weak form, ruled by Mr. Radio 🦉 2026-09-17.

WHY THIS FILE EXISTS: §6 item 19 was a convention, and a rule that depends on
remembering is not installed. Nine test files already claim a parity row key in
their header; two of them name the legacy coordinate they mirror. Nothing
noticed the other seven, because nothing was looking.

THE RECOGNISER IS THE CLAIM, NOT THE CITATION. The obvious predicate — "a
parity test is one that cites a legacy file:line" — is a tautology: the citation
IS the thing being checked, so a test that forgot its citation is invisible to a
guard that finds parity tests by their citations. Such a guard is green on an
empty set and can never report a violation. So the population here is DECLARED:
a test opts in by naming its build-item row key in its header comment
("Parity A-0", "parity A-2 #2b"), and the row key must be one the manifest
actually lists. The denominator is the manifest's 42 row keys, and this file
asserts that denominator before it asserts anything about the tests.

"HEADER COMMENT", NOT "DOCSTRING". Item 19's cell said docstring; these are
TypeScript files and have none. The header is the first HEADER_LINES lines.

WEAK FORM AND STRONG FORM — BOTH ARE HERE. Weak: the coordinate is PRESENT
and well-formed. Strong (Mr. Radio 🦉's ruling, 2026-09-18): the coordinate
RESOLVES at HEAD —
  - a notifications.js citation names a legacy METHOD on its header line, and
    its whole line range falls inside that method's body (the `name(…) {` line
    through its closing brace);
  - a notifications.html citation names an element ID, and its whole range
    falls between that element's open tag and its matching close tag, found by
    PARSING the markup, not by counting lines;
  - the named method or id must appear in a note the row derives from
    (`io/phase2/A<n>.md`, as the manifest row cites it); a row with no note,
    like A-0, is held to the name in its own header instead;
  - a citation that names no method or id is red: the header must name one.

WHY BY NAME AND NOT BY THE NOTE'S LINE NUMBERS. The io/phase2 notes were read
off an older notifications.js, and their coordinates had already drifted when
they were committed (A3 R3 cites `js:21636-21645`; at f63350e3 that is another
method). A range check against them would reject citations that are right
today. A method or id name survives the drift; a line number does not.

"ON ITS HEADER LINE" means the same line as the coordinate or the line just
above it, so a wrapped comment still counts. Every name on that line is a
candidate, and the citation resolves if ANY of them contains the whole range:
a prose word that happens to be a method name can widen the candidates, but it
cannot make a range resolve that is not inside that method.
"""

from html.parser import HTMLParser

import re

from pathlib import Path

import pytest

import cosa.utils.util as cu


MANIFEST_REL = "src/rnd/v0.2.1/2026.09.16-parity-build-row-manifest.md"

# The first N lines of a test file are its header comment. Generous enough to
# clear a licence block, tight enough that a citation buried beside an
# assertion 200 lines down does not count as naming the test's source.
HEADER_LINES = 12

# A row key as the manifest's summary table writes it: A-0, A-1c3, A-2 #2b, B-7,
# and also B-1b and B-5L.
#
# 🔴 THIS WAS AN ENUMERATION AND IT WAS WRONG. The first cut spelled the two
# halves differently — `A-\d+[a-z]?\d*` for the A rows and a bare `B-\d+` for
# the B rows — because every B key visible at a glance was a bare number. `B-1b`
# and `B-5L` are not, so the guard's denominator read 42 against a table of 44
# and said nothing: a floor of `>= 40` cannot see two keys it never parsed, and
# any test claiming one of them would have been reported as claiming a row the
# manifest does not list. Caught by Mr. Radio 🦉 on 2026-09-17 against a peer's
# count of 44.
#
# So this is one predicate for both halves, and the case class is [A-Za-z]
# rather than [a-z] because `B-5L` is capitalised. The shape is: a phase letter,
# a number, an optional letter-and-number suffix, and an optional ` #N` item
# with its own optional letter.
ROW_KEY = r"(?:[AB]-\d+[A-Za-z]?\d*(?:\s*#\d+[A-Za-z]?)?)"

# A test opts in by naming its row key after the word "parity", in any case.
# This is the OLD SHAPE. It is prose, and prose cannot tell a declaration from a
# mention — see TRANSITIONAL ARM below.
CLAIMS_A_ROW = re.compile( r"parity\s+(" + ROW_KEY + r")", re.IGNORECASE )

# ---------------------------------------------------------------------------
# S1 — THE STRUCTURED MARKER
# ---------------------------------------------------------------------------
#
# 🔴 THE RECOGNISER IS THE WHOLE PROBLEM, AND PROSE CANNOT SOLVE IT. A prose
# recogniser cannot distinguish a test DECLARING its row from a passage MENTIONING
# one. Two live files prove it, and neither is a claim:
#
#   notifications_js/both_clients_issue_the_same_request_for_every_control.test.ts:30
#       `//   mux   HoldingAreaStore   patchTask   PATCH /api/tasks/{id}  (parity A-2 #0)`
#       — a TABLE ROW. 0 legacy coordinates anywhere in that file.
#   this file, line 16
#       `("Parity A-0", "parity A-2 #2b"), and the row key must be one the manifest`
#       — THIS GUARD'S OWN DOCSTRING explaining its own format. A prose recogniser
#       wide enough to see them makes the guard police itself.
#
# Both sit outside the 12-line window TODAY, which is luck, not a control: they are
# at lines 30 and 16 of files whose headers happen to be long. Widen the window and
# they walk in. Measured by Maya 2026-09-19: every header-window variant admits both.
#
# THE MARKER IS DEFINED BY PLACEMENT, and that is what makes it immune. It is the
# FIRST content on its line after an optional comment leader. A table row has columns
# before it; a docstring example has quotes and prose before it. Neither can produce
# a marker no matter how wide the window gets.
PARITY_MARKER = re.compile(
    r"^[ \t]*(?://+|\#+|\*)?[ \t]*PARITY-(CLAIM|EXEMPT):[ \t]*(" + ROW_KEY + r")[ \t]*(.*)$"
)

# 🔴 A NEAR MISS IS THE DANGEROUS CASE, BECAUSE IT FAILS SILENTLY.
# A file that writes a marker and gets the syntax wrong matches NEITHER the marker
# nor — once the attempt has pushed its prose claim past the header window — the
# transitional arm. It leaves the declared population altogether, and every rule in
# this file then has one fewer file to be right about. Nothing reddens.
#
# MEASURED 2026-09-19 on this tree: `PARITY-EXEMPTED:`, `PARITY EXEMPT:` and a
# missing colon each took the one exempt file from (claims 31, exempt 1) to
# (claims 31, exempt 0) — a file in NEITHER census, and the population floor did not
# notice because it is measured on the other glob.
#
# This pattern is LOOSER than PARITY_MARKER — it recognises the ATTEMPT — but it is
# not loose in the way that matters, and the first cut WAS.
#
# ⚠️ THAT FIRST CUT WAS CASE-INSENSITIVE AND IT FALSELY ACCUSED A REAL FILE on its
# first run: `render/fleet_size_cap_dial_parity.test.ts` line 11 reads "because the
# parity claim is the pair" — ordinary English. A case-insensitive predicate turns
# prose into a declaration, which is the exact defect this whole commit exists to
# fix, reintroduced by the detector meant to protect it.
#
# So: the token must be SHOUTED, which is what a marker is, AND it must be followed
# by a row key. Prose does not shout and does not carry a row key immediately after
# the words. `PARITY-EXEMPTED:`, `PARITY EXEMPT:` and a missing colon all still match.
NEAR_MISS_MARKER = re.compile( r"PARITY[ _-]*(?:CLAIM|EXEMPT)\w*\s*:?\s*" + ROW_KEY )

# An exemption must say WHY, on the same line. Precedent: stylelint refuses a waiver
# without a same-line reason (`.stylelintrc.json:3`, `run-stylelint-gate.sh:85`).
# An em-dash or a double hyphen opens the reason.
EXEMPT_REASON = re.compile( r"^\s*(?:—|--|-)\s*(\S.*)$" )


# ---------------------------------------------------------------------------
# THE TRANSITIONAL ARM — how the old shape survives without a flag day
# ---------------------------------------------------------------------------
#
# Every one of the live `.test.ts` claims uses the old prose shape. A marker-ONLY
# recogniser would take the claiming census to ZERO, and a guard policing an empty
# set is green forever — the exact tautology this file's own header warns about.
# So the old shape keeps working, behind two filters that reject both known negatives.
#
# 🔴 THESE TWO FILTERS ARE A PROXY, NOT THE PREDICATE, AND THEY HAVE NO DENOMINATOR.
# They were FITTED to the two negatives we happened to find. Nothing here says a third
# prose shape does not exist. That is why the arm is SELF-RETIRING rather than
# permanent: `test_the_old_shape_count_only_shrinks` pins the count, it may only go
# down, and when it reaches zero these filters and this comment come out together.
# A prose caveat would protect only the reader who reads it; the count is mechanical.

def strip_comment_leader( line ):
    """The line's content, with `//`, `#` or a docstring `*` removed."""
    return re.sub( r"^\s*(?://+|\#+|\*)\s*", "", line )


def is_table_row( line ):
    """
    Two or more runs of 2+ spaces between non-space text = columns, not a sentence.

    Requires:
        - line is a single physical line

    Ensures:
        - returns True for an aligned table row, False for ordinary prose
    """
    return len( re.findall( r"\S {2,}(?=\S)", strip_comment_leader( line ).rstrip() ) ) >= 2


def is_inside_quotes( line, idx ):
    """
    Whether position `idx` falls inside a quoted span on `line`.

    Requires:
        - 0 <= idx < len( line )

    Ensures:
        - returns True when idx sits between a matched pair of single or double
          quotes, which is what a docstring's own format example looks like
    """
    for match in re.finditer( r"\"[^\"]*\"|'[^']*'", line ):
        if match.start() < idx < match.end(): return True
    return False


def old_shape_claim( header ):
    """
    The row key this header claims in the OLD prose shape, or None.

    Ensures:
        - returns the row key only when the claim is neither a table row nor
          inside quotes — the two shapes measured to be mentions, not declarations
        - returns None when the header carries no parity mention at all
    """
    for line in header.splitlines():
        match = CLAIMS_A_ROW.search( line )
        if match is None: continue
        if is_table_row( line ): continue
        if is_inside_quotes( line, match.start() ): continue
        return match.group( 1 )
    return None


def marker_near_miss( header ):
    """
    Whether this header REACHES for a parity marker but does not produce one.

    Requires:
        - header is the file's leading lines

    Ensures:
        - True when the header contains a marker-shaped token that PARITY_MARKER
          does not match — a typo, a missing colon, a marker indented behind prose
        - False for a well-formed marker, and False for a header that never tried
    """
    if marker_claim( header ) is not None: return False
    return NEAR_MISS_MARKER.search( header ) is not None


def exemption_has_rotted( header ):
    """
    Whether this header declares PARITY-EXEMPT and then names a legacy coordinate.

    Requires:
        - header is the file's leading lines

    Ensures:
        - True only when BOTH an EXEMPT marker and a legacy coordinate are present
        - False for a non-exempt header, whatever it cites
    """
    marker = marker_claim( header )
    if marker is None or marker[ 0 ] != "EXEMPT": return False
    return LEGACY_COORD.search( header ) is not None


def marker_claim( header ):
    """
    ( kind, row_key, reason ) from this header's PARITY marker, or None.

    Ensures:
        - kind is "CLAIM" or "EXEMPT"
        - reason is the text after the row key for an EXEMPT, else ""
        - returns the FIRST marker; a second one is caught by its own test
    """
    for line in header.splitlines():
        match = PARITY_MARKER.match( line )
        if match is None: continue
        kind, key, rest = match.group( 1 ), match.group( 2 ), match.group( 3 )
        reason = EXEMPT_REASON.match( rest )
        return ( kind, key, reason.group( 1 ).strip() if reason else "" )
    return None

# The legacy client is two files, and a coordinate is a line or a line range.
LEGACY_COORD = re.compile( r"notifications\.(?:js|html):\d+(?:-\d+)?" )

# The same, capturing its parts, for the strong form.
LEGACY_CITE = re.compile( r"notifications\.(js|html):(\d+)(?:-(\d+))?" )

# A SYMBOL citation — `notifications.js  someMethod`, whitespace after the filename
# rather than a colon, which is what keeps it from matching the coordinate form above.
# Several names may share one line (`playInstantTTS / playReliableTTS`).
#
# 🔴 WHY THIS SHAPE IS ACCEPTED AT ALL, ruled by Mr. Radio 🦉 2026-09-27. The manifest's
# standing rule 1 — his, written 2026-09-19 — says "cite the anchor text and the symbol,
# NEVER the line number. A line number goes stale the moment anyone edits above it, and a
# stale coordinate does not announce itself." This guard used to demand exactly the shape
# that rule forbids, so seven files obeying the rule were scored as defects.
#
# The evidence is in the tree, not in the argument: every one of the 45 citation defects
# `test_a_parity_citation_resolves_inside_what_it_names` reports is a ROTTED LINE NUMBER.
# Zero are rotted symbols. Measured 2026-09-27 at 7db04b8af.
LEGACY_SYMBOL = re.compile( r"notifications\.js[ \t]+([A-Za-z_$][\w$]*(?:[ \t]*/[ \t]*[A-Za-z_$][\w$]*)*)" )

# The OTHER shape the tree actually uses, and the better one: the header declares the
# file once, then lists backticked symbols beneath it —
#
#     // ... All in src/lupin_app/static/js/notifications.js:
#     //   - `_formatTaskListCount`      :11176  "Live: L" · ...
#
# Recognised only when the header names notifications.js, so a backticked word in an
# unrelated header is not mistaken for a citation. The uniqueness check below is what
# makes this safe: a backticked word that is not a real method resolves nowhere and is
# reported, rather than quietly satisfying the rule.
LEGACY_FILE_DECL = re.compile( r"notifications\.js" )
BACKTICKED       = re.compile( r"`([A-Za-z_$][\w$]*)`" )

# ---------------------------------------------------------------------------
# THE SAME RULE FOR notifications.html — ruled by Mr. Radio 🦉 2026-09-27
# ---------------------------------------------------------------------------
#
# 🔴 THE SYMBOL FORM WAS js-ONLY, SO EVERY html CITATION HAD TO BE A LINE NUMBER — the
# one shape standing rule 1 forbids. `LEGACY_SYMBOL` names `notifications.js`, so a test
# mirroring markup had no rot-proof form available to it and was obliged to cite a
# coordinate that would rot at the next edit above it.
#
# WHY THIS IS NOT THE js PATTERN WITH THE FILENAME SWAPPED. An html citation can mean two
# different things, and `#` is the discriminator:
#
#     notifications.html  #tts-queue-section   an ELEMENT, resolved in html_element_spans
#     notifications.html  toggleSection        a DECLARATION in an inline <script>
#
# ⚠️ AND THE SECOND POPULATION IS THE ONE A READER DOES NOT EXPECT, so it is named here
# rather than left to be discovered: `notifications.html` carries 17 inline `<script>`
# blocks, and four parity tests cite identifiers inside them —
# `LUPIN_ACCORDION_PERSIST_KEYS`, `toggleSection`, `applyPersistedAccordions`. Those are
# not elements and never will be; before this rule they had no honest citation at all, and
# forcing them to name an element would have pointed a header at markup its test never
# touches. An id may carry dashes, which a JS identifier may not, which is the other reason
# these are two patterns and not one.
#
# The uniqueness condition is the same and it is not decoration: `content` is declared at
# 1558 AND 1601 inside those scripts, so a header citing `content` alone names neither.
# Element ids are all unique in the file today (252 of them, measured 2026-09-27), so the
# duplicate arm of THIS rule is exercised by the inline-script half — see
# `test_a_duplicated_inline_script_name_is_not_a_citation`.
LEGACY_HTML_SYMBOL = re.compile( r"notifications\.html[ \t]+(#?)([A-Za-z_$][\w$-]*)" )
LEGACY_HTML_DECL   = re.compile( r"notifications\.html" )
BACKTICKED_ID      = re.compile( r"`#([A-Za-z_][\w-]*)`" )

# A DECLARATION inside an inline script: a function, or a const/let/var binding. Anchored
# at the start of its line so a CALL or a reference declares nothing, and applied only to
# the text inside <script> … </script> so prose in the markup cannot declare either.
HTML_SCRIPT      = re.compile( r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE )
HTML_SCRIPT_DECL = re.compile(
    r"^[ \t]*(?:async[ \t]+)?function[ \t]+([A-Za-z_$][\w$]*)"
    r"|^[ \t]*(?:const|let|var)[ \t]+([A-Za-z_$][\w$]*)",
    re.MULTILINE )


def html_inline_script_names( source ):
    """
    Every name declared inside notifications.html's inline scripts, with its lines.

    Requires:
        - source is the text of notifications.html

    Ensures:
        - returns { name: [ line, ... ] }, 1-based, in file order; a name declared
          twice keeps both lines, because the uniqueness condition needs the count
        - only `<script>` contents are read, so markup text declares nothing
        - a call or a reference is not a declaration — the pattern is anchored at
          the start of a line

    Raises:
        - None
    """
    names = {}
    for block in HTML_SCRIPT.finditer( source ):
        base = source[ :block.start( 1 ) ].count( "\n" ) + 1
        for decl in HTML_SCRIPT_DECL.finditer( block.group( 1 ) ):
            name = decl.group( 1 ) or decl.group( 2 )
            names.setdefault( name, [] ).append(
                base + block.group( 1 )[ :decl.start() ].count( "\n" ) )
    return names


def html_symbol_citation_defects( header, spans, script_names ):
    """
    Why a header's notifications.html symbol citations do NOT satisfy the guard.

    The html counterpart of `symbol_citation_defects`, with the same one-good-citation
    rule and the same uniqueness condition. `#` picks the population: `#foo` is an
    element id, a bare `foo` is a declaration in an inline script.

    Requires:
        - header is the file's first HEADER_LINES lines
        - spans is `html_element_spans( notifications.html )`
        - script_names is `html_inline_script_names( notifications.html )`

    Ensures:
        - returns ( True, [] ) when at least one cited id or script name resolves
          exactly once
        - returns ( False, defects ) otherwise, naming every citation and WHY, with a
          DIFFERENT reason for a name that is absent and one that is declared twice —
          the two need different work and a single message hides which you have
        - returns ( False, [] ) when the header cites no html symbol at all

    Raises:
        - None
    """
    ids, names = [], []
    for match in LEGACY_HTML_SYMBOL.finditer( header ):
        ( ids if match.group( 1 ) == "#" else names ).append( match.group( 2 ) )
    if LEGACY_HTML_DECL.search( header ):
        ids += BACKTICKED_ID.findall( header )
        names += [ n for n in BACKTICKED.findall( header ) if n in script_names ]

    # No early return for "nothing cited": with both lists empty the loops below run zero
    # times and fall through to ( False, [] ), which is the contract. The js function keeps
    # an explicit `if not cited` guard, and a line that cannot change any outcome cannot be
    # falsified by a test either — so this one is left out rather than mirrored for symmetry.
    defects = []
    for cited, table, what, render in (
        ( ids,   spans,        "element id",         lambda v: _spans( v ) ),
        ( names, script_names, "inline-script name", lambda v: "; ".join( str( n ) for n in v ) ),
    ):
        for name in dict.fromkeys( cited ):
            found = table.get( name, [] )
            if   len( found ) == 1: return ( True, [] )   # one good citation is enough
            elif not found:         defects.append( ( name, f"no such {what} in notifications.html" ) )
            else:                   defects.append( (
                name,
                f"declared {len( found )} times ({render( found )}) — "
                f"a {what} that resolves twice names neither" ) )
    return ( False, defects )


def symbol_citation_defects( header, bodies ):
    """
    Why a header's symbol citations do NOT satisfy the guard, one reason per symbol.

    🔴 A SYMBOL IS ONLY A COORDINATE WHEN IT RESOLVES EXACTLY ONCE (Mr. Radio, 2026-09-27).
    `notifications.js` defines `playAudioBlob` twice, at 4353-4383 and 5032-5097. A reader
    handed that name cannot tell which body the test mirrors, and neither can this guard —
    so a duplicate name is still a defect, exactly as a rotted line number is. Trading a
    coordinate that points at the wrong place for a name that points at two places is not
    an improvement.

    Requires:
        - header is the file's first HEADER_LINES lines
        - bodies is `js_method_bodies( notifications.js )`

    Ensures:
        - returns ( True, [] ) when at least one cited symbol resolves exactly once —
          the header is satisfied, and a second, vaguer citation beside it is not held
          against it
        - returns ( False, defects ) otherwise, naming every symbol cited and WHY it
          does not resolve, so the failure says which one rather than only that the
          header is wrong
        - returns ( False, [] ) when the header cites no symbol at all

    ⚠️ The satisfied flag is SEPARATE from the defect list on purpose. An earlier cut
    returned the list alone, and an empty list then meant two different things — "a
    symbol resolved" and "there were no symbols" — so the caller had to re-derive which,
    and got it wrong. A return value satisfiable by more than one state cannot tell the
    caller which one happened.

    Raises:
        - None
    """
    cited = [ name.strip()
              for match in LEGACY_SYMBOL.finditer( header )
              for name in match.group( 1 ).split( "/" ) ]
    if LEGACY_FILE_DECL.search( header ):
        cited += BACKTICKED.findall( header )
    if not cited: return ( False, [] )

    defects = []
    for name in cited:
        spans = bodies.get( name, [] )
        if   len( spans ) == 1: return ( True, [] )   # one good citation is enough
        elif not spans:         defects.append( ( name, "no such symbol in notifications.js" ) )
        else:                   defects.append( ( name, f"defined {len( spans )} times ({_spans( spans )}) — a symbol that resolves twice names neither" ) )
    return ( False, defects )


def _spans( spans ):
    return "; ".join( f"{a}-{b}" for a, b in spans )


LEGACY_JS_REL   = "src/lupin_app/static/js/notifications.js"
LEGACY_HTML_REL = "src/lupin_app/static/html/notifications.html"
PHASE2_DIR_REL  = "io/phase2"

# A method or function DEFINITION whose `{` ends the line: a class method at
# four spaces, or a top-level function. Its body closes on the first later line
# that is exactly the same indent plus `}`. Measured 2026-09-18 at 2847ea74:
# 617 definitions, every one closing before the next begins.
JS_DEF = re.compile( r"^(    |)(?:async\s+)?(?:function\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{\s*$" )
JS_KEYWORDS = frozenset( { "if", "for", "while", "switch", "catch", "function" } )

# A name a header line might carry: a JS identifier, or an element id with or
# without its leading `#`.
NAME_TOKEN = re.compile( r"#?([A-Za-z_$][\w$-]*)" )

# The manifest's detail block names its notes as "Phase 2 A3 R3 / A4 item 6".
NOTE_REF = re.compile( r"\bA(\d{1,2})\b" )

# HTML elements that never have a close tag.
VOID_TAGS = frozenset( {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "source", "track", "wbr",
} )

# The manifest's summary table: | Row key | Title | Pri | Depends-on |
MANIFEST_ROW = re.compile( r"^\|\s*(" + ROW_KEY + r")\s*\|" )

# ---------------------------------------------------------------------------
# THE TWO RATCHETS — both MEASURED at f53aa9d9 on 2026-09-19, not chosen
# ---------------------------------------------------------------------------
#
#     .test.ts only (pre-S4)   claims=27  exempt=0  declared=27  old_shape=27
#     both languages (S4)      claims=31  exempt=1  declared=32  old_shape=27
#
# 🔴 THE DECLARED POPULATION IS PINNED AS A SET, NOT AS A COUNT OR A FLOOR.
#
# The first cut of this was `total >= DECLARED_POPULATION_FLOOR`, and a `>=` floor
# protects the population only down to its LAST MANUAL UPDATE. Grow to 40, leave the
# floor at 32, drift back to 32 — and the assertion passes. A floor decays into a
# historical footnote while still looking like a control.
#
# A COUNT IS NOT AN IDENTITY EITHER (Maya 🌻, 2026-09-19): a set can lose one file and
# gain another and keep its cardinality exactly. Both halves of that swap are things
# this guard exists to notice, and neither moves a number.
#
# So the pin is the SET, the count is `len()` of it, and nothing restates it. Two
# artifacts encoding one rule agree until they do not.
#
# ⚠️ THIS ENUMERATION IS NOT AN APPROXIMATION OF A PREDICATE — it is the RECORDED
# RESULT of one. The predicate is `parity_census`, which runs on every invocation;
# this is what it returned at the S4 sha, held so that a later disagreement is
# reported instead of absorbed. That is the opposite of an enumeration standing in
# FOR a rule nobody wrote.
# 🔴 HOW THIS LITERAL WAS CHECKED, AND HOW TO CHECK IT AGAIN — the recipe is here
# because the check itself is NOT a test and never will be.
#
# This frozenset was GENERATED by running `parity_census`. So `pin == live` at the
# sha it was taken from is TRIVIALLY true and is evidence of nothing but a correct
# snapshot. The assertion holds the LIVE TREE to this literal; nothing holds this
# literal to anything. A careless edit here still passes.
#
# It was checked ONCE, at review time, against a derivation that never imports this
# module — and a check performed once by a reviewer, in a session that then ends,
# leaves no trace in the artifact. So the COMMAND lives here, with the numbers it
# produced, and re-deriving is one paste rather than an act of memory:
#
#     git ls-files 'src/tests/**/*.test.ts' | wc -l
#     git ls-files 'src/tests/**/*.test.ts' | while read f; do \
#         head -12 "$f" | grep -qiE 'parity +[AB]-[0-9]' && echo "$f"; done | wc -l
#     git ls-files 'src/tests/**/*.py' | while read f; do \
#         head -12 "$f" | grep -qE '^[ \t]*(#+)?[ \t]*PARITY-(CLAIM|EXEMPT):' && echo "$f"; done | wc -l
#     git ls-files 'src/tests/**/*.py' | while read f; do \
#         head -12 "$f" | grep -qE '^[ \t]*(#+)?[ \t]*PARITY-EXEMPT:' && echo "$f"; done | wc -l
#
# At e057ed90, 2026-09-19:  269 tracked .test.ts · 27 prose claims · 5 .py markers ·
# 1 of them EXEMPT  =>  27 + 4 + 1 = 32, matching len( DECLARED_POPULATION ).
#
# ⚠️ DELIBERATELY NOT A TEST. A second derivation of the same rule agrees with the
# first until it does not, and when they disagree neither side can arbitrate — you
# get a coincidence to maintain instead of a fact. This is a REVIEWER'S RECIPE: run
# it when you change the pin, and put the four numbers in the commit message.
DECLARED_POPULATION = frozenset( {
    "src/tests/e2e_ui/test_multiplexer_action_required_card_parity.py",
    "src/tests/e2e_ui/test_multiplexer_fleet_size_cap_dial.py",
    "src/tests/e2e_ui/test_multiplexer_holding_area_flow_ratio.py",
    "src/tests/e2e_ui/test_multiplexer_jobs_pane_legacy_words.py",
    "src/tests/unit/multiplexer/action_required_persistence.test.ts",
    "src/tests/unit/multiplexer/action_required_tts_deferral.test.ts",
    "src/tests/unit/multiplexer/audio/direct_tts_playback_port.test.ts",
    "src/tests/unit/multiplexer/audio_store.test.ts",
    "src/tests/unit/multiplexer/boot_wires_action_required_to_reveal_through_the_toolbar.test.ts",
    "src/tests/unit/multiplexer/boot_wires_both_filter_badges_to_the_reveal.test.ts",
    "src/tests/unit/multiplexer/boot_wires_direct_tts_to_the_shared_queue_and_the_halt.test.ts",
    "src/tests/unit/multiplexer/debug_sink_parity.test.ts",
    "src/tests/unit/multiplexer/qa_store.test.ts",
    "src/tests/unit/multiplexer/render/action_required_auto_reveal.test.ts",
    "src/tests/unit/multiplexer/render/action_required_cancel.test.ts",
    "src/tests/unit/multiplexer/render/action_required_chrome.test.ts",
    "src/tests/unit/multiplexer/render/action_required_keyboard.test.ts",
    "src/tests/unit/multiplexer/render/action_required_multiple_choice_other.test.ts",
    "src/tests/unit/multiplexer/render/action_required_neither_and_default.test.ts",
    "src/tests/unit/multiplexer/render/action_required_open_ended_mic.test.ts",
    "src/tests/unit/multiplexer/render/action_required_pause.test.ts",
    "src/tests/unit/multiplexer/render/action_required_progress.test.ts",
    "src/tests/unit/multiplexer/render/action_required_tts_deferral_render.test.ts",
    "src/tests/unit/multiplexer/render/action_required_yes_no_comment.test.ts",
    "src/tests/unit/multiplexer/render/debug_panel_renderer_parity.test.ts",
    "src/tests/unit/multiplexer/render/direct_tts_renderer_parity.test.ts",
    "src/tests/unit/multiplexer/render/filter_settings_reveal.test.ts",
    "src/tests/unit/multiplexer/render/fleet_size_cap_dial_parity.test.ts",
    "src/tests/unit/multiplexer/render/flow_ratio_model_and_banner.test.ts",
    "src/tests/unit/multiplexer/render/holding_area_flow_ratio_parity.test.ts",
    "src/tests/unit/multiplexer/render/notifications_list_tts_interaction_mode.test.ts",
    "src/tests/unit/multiplexer/render/notifications_list_tts_reveal.test.ts",
    "src/tests/unit/multiplexer/render/qa_pane_renderer.test.ts",
    "src/tests/unit/multiplexer/render/scroll_reveal.test.ts",
    "src/tests/unit/multiplexer/render/section_collapse_persist_parity.test.ts",
    "src/tests/unit/multiplexer/render/shared_row_controls_reach_every_pane.test.ts",
    "src/tests/unit/multiplexer/render/submit_jobs_pane_renderer.test.ts",
    "src/tests/unit/multiplexer/render/system_status_renderer_parity.test.ts",
    "src/tests/unit/multiplexer/render/task_list_counts_and_truncation_parity.test.ts",
    "src/tests/unit/multiplexer/render/the_jobs_pane_speaks_the_legacy_words.test.ts",
    "src/tests/unit/multiplexer/render/time_saved_renderer_parity.test.ts",
    "src/tests/unit/multiplexer/render/tts_header_state_parity.test.ts",
    "src/tests/unit/multiplexer/render/tts_pane_visibility_parity.test.ts",
    "src/tests/unit/multiplexer/render/tts_pause_play_parity.test.ts",
    "src/tests/unit/multiplexer/submit_jobs_store.test.ts",
    "src/tests/unit/multiplexer/tts_manual_pause_blocks_advance_parity.test.ts",
    "src/tests/unit/multiplexer/tts_playing_signal.test.ts",
    "src/tests/unit/multiplexer/tts_queue_persistence.test.ts",
    "src/tests/unit/multiplexer/wire_qa_metrics.test.ts",
    "src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts",
    "src/tests/unit/test_every_toggled_section_honours_the_hidden_attribute.py",
} )

# OLD_SHAPE_CEILING may only be LOWERED. It is the transitional arm's blast radius,
# and the arm is deleted when this reaches 0. A new file uses `PARITY-CLAIM:`.
#
# UNCHANGED BY S4, which is worth stating: widening the glob pulled in five Python
# parity files, and every one of them declares with a MARKER — the four claims were
# converted as S4's prerequisite, the fifth is the exemption. So the old prose shape
# is now exactly the 27 TypeScript files it started as, and the retirement it is
# counting down has a fixed target rather than a growing one.
OLD_SHAPE_CEILING = 27

# Seven files claimed a row key before this guard existed and none of them names
# its legacy source. They are GRANDFATHERED so the guard can land green, and the
# list is a CEILING, not a floor: `test_the_grandfather_list_only_shrinks`
# fails when an entry stops violating, so the list cannot outlive the debt it
# records. Do not add to it — a new parity test names its source or goes red.
GRANDFATHERED = frozenset( {
    "src/tests/unit/multiplexer/action_required_persistence.test.ts",
    "src/tests/unit/multiplexer/boot_wires_action_required_to_reveal_through_the_toolbar.test.ts",
    "src/tests/unit/multiplexer/render/action_required_cancel.test.ts",
    "src/tests/unit/multiplexer/render/action_required_pause.test.ts",
    "src/tests/unit/multiplexer/render/action_required_progress.test.ts",
    "src/tests/unit/multiplexer/render/shared_row_controls_reach_every_pane.test.ts",
    "src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts",
} )


def js_method_bodies( source ):
    """
    Every legacy method or function body, by name.

    Requires:
        - source is the text of notifications.js

    Ensures:
        - returns { name: [ ( def_line, close_line ), ... ] }, 1-based and
          inclusive; a name defined twice keeps both spans
        - a definition whose closing brace cannot be found is left out, so a
          citation of it goes red rather than resolving against a guess
    """
    lines  = source.splitlines()
    bodies = {}
    for i, line in enumerate( lines ):
        match = JS_DEF.match( line )
        if match is None or match.group( 2 ) in JS_KEYWORDS: continue
        close = match.group( 1 ) + "}"
        end   = next( ( j for j in range( i + 1, len( lines ) ) if lines[ j ].rstrip() == close ), None )
        if end is None: continue
        bodies.setdefault( match.group( 2 ), [] ).append( ( i + 1, end + 1 ) )
    return bodies


class _ElementSpans( HTMLParser ):
    """Records each id-bearing element's span from its open tag to its matching close tag."""

    def __init__( self ):
        super().__init__( convert_charrefs=True )
        self.stack = []
        self.spans = {}

    def handle_starttag( self, tag, attrs ):
        if tag in VOID_TAGS: return
        self.stack.append( ( tag, dict( attrs ).get( "id" ), self.getpos()[ 0 ] ) )

    def handle_endtag( self, tag ):
        # Pop to the matching open tag; anything above it was left unclosed.
        for depth in range( len( self.stack ) - 1, -1, -1 ):
            if self.stack[ depth ][ 0 ] != tag: continue
            _, element_id, start = self.stack[ depth ]
            if element_id: self.spans.setdefault( element_id, [] ).append( ( start, self.getpos()[ 0 ] ) )
            del self.stack[ depth: ]
            return


def html_element_spans( source ):
    """
    Every id-bearing element's span, by id.

    Requires:
        - source is the text of notifications.html

    Ensures:
        - returns { id: [ ( open_line, close_line ), ... ] }, 1-based and
          inclusive, from the line the open tag starts on to the line of its
          matching close tag — parsed, never counted
        - an element whose close tag never arrives is left out
    """
    parser = _ElementSpans()
    parser.feed( source )
    parser.close()
    return parser.spans


def row_notes( manifest_text, row_key, note_dir ):
    """
    The io/phase2 notes a manifest row derives from.

    Requires:
        - manifest_text is the manifest; note_dir is the io/phase2 directory

    Ensures:
        - returns the texts of every `A<n>.md` the row's detail block names
          (its bold `**<key> ·` line through the next blank line) that exists
        - a row that names no note returns an empty list
    """
    lines = manifest_text.splitlines()
    want  = _normalize( row_key )
    start = next(
        ( i for i, line in enumerate( lines )
          if line.startswith( "**" ) and _normalize( line[ 2: ].split( "·" )[ 0 ] ) == want ),
        None,
    )
    if start is None: return []
    block = []
    for line in lines[ start: ]:
        if not line.strip(): break
        block.append( line )
    names = sorted( set( NOTE_REF.findall( " ".join( block ) ) ), key=int )
    return [ ( note_dir / f"A{n}.md" ).read_text( encoding="utf-8" )
             for n in names if ( note_dir / f"A{n}.md" ).is_file() ]


# The one reason that is NOT a defect in the test. Named once, so the producer and
# the reporter cannot drift apart into two spellings of the same idea.
NOTE_REASON = "is not named in the row's note"


def report_by_class( offenders ):
    """
    The failure text, split by DEFECT CLASS, naming the artifact that holds each.

    Requires:
        - offenders is [ ( test_path, row_key, citation, reason ), ... ]

    Ensures:
        - returns a string with one section per class present, and no section for
          a class with no offenders
        - a CITATION section names the TEST as the thing to edit
        - a NOTE section names the io/phase2 note and says not to edit the test
        - every offender appears in exactly one section

    Why it is its own function rather than inline in the assertion: an assertion
    message only renders on failure, so logic living there is unguarded by
    construction — the suite is green whether it is right or wrong. Measured
    2026-09-19 (Maya 🌻): the first cut of this lived inline, added no test, and
    left the test count unchanged at 15.
    """
    note_defects = [ o for o in offenders if NOTE_REASON in o[ 3 ] ]
    cite_defects = [ o for o in offenders if NOTE_REASON not in o[ 3 ] ]

    report = []
    if cite_defects:
        report.append(
            f"{len( cite_defects )} CITATION defect(s) — FIX THE TEST'S HEADER. A "
            "notifications.js citation names its legacy method on the same header line "
            "and falls inside that method's body; a notifications.html citation names "
            "its element id and falls between that element's open and close tags:\n  "
            + "\n  ".join( f"{path} ({key}) {cite}: {reason}" for path, key, cite, reason in cite_defects )
        )
    if note_defects:
        report.append(
            f"{len( note_defects )} NOTE defect(s) — DO NOT EDIT THE TEST. Its citation "
            f"resolves; the row's note under {PHASE2_DIR_REL}/ does not name the method, "
            "so add the method to the note (or correct the note's row key):\n  "
            + "\n  ".join( f"{PHASE2_DIR_REL}/ note for row {key} is missing "
                            f"{reason.split( ' ' + NOTE_REASON )[ 0 ]}  (cited by {path} as {cite})"
                            for path, key, cite, reason in note_defects )
        )
    return "\n\n".join( report )


def unresolved_citations( header, bodies, spans, notes ):
    """
    Every legacy citation in a header that does NOT resolve, with the reason.

    Requires:
        - header is a test file's first HEADER_LINES lines
        - bodies / spans come from js_method_bodies / html_element_spans at HEAD
        - notes is row_notes() for the row the header claims

    Ensures:
        - returns [ ( citation, reason ), ... ], empty when every citation resolves
        - a citation resolves iff a name on its line (or the line above) is a
          legacy method (js) or element id (html) whose span contains the WHOLE
          cited range, and — when the row has notes — that name appears in one
    """
    lines    = header.splitlines()
    problems = []
    for index, line in enumerate( lines ):
        for cite in LEGACY_CITE.finditer( line ):
            kind   = cite.group( 1 )
            first  = int( cite.group( 2 ) )
            last   = int( cite.group( 3 ) or cite.group( 2 ) )
            table  = bodies if kind == "js" else spans
            what   = "method" if kind == "js" else "element id"
            nearby = line + " " + ( lines[ index - 1 ] if index > 0 else "" )
            named  = [ t for t in dict.fromkeys( NAME_TOKEN.findall( nearby ) ) if t in table ]
            if not named:
                problems.append( ( cite.group( 0 ), f"names no legacy {what} on its line" ) )
                continue
            if last < first:
                problems.append( ( cite.group( 0 ), "range runs backwards" ) )
                continue
            holders = [ n for n in named if any( a <= first and last <= b for a, b in table[ n ] ) ]
            if not holders:
                where = "; ".join( f"{n} is {a}-{b}" for n in named for a, b in table[ n ] )
                problems.append( ( cite.group( 0 ), f"not inside the {what} it names ({where})" ) )
                continue
            if notes and not any( re.search( r"(?<![\w$-])" + re.escape( n ) + r"(?![\w$-])", note )
                                  for n in holders for note in notes ):
                problems.append( ( cite.group( 0 ), f"{', '.join( holders )} {NOTE_REASON}" ) )
    return problems


def _normalize( row_key ):
    """
    Collapse a row key to a comparable form.

    Requires:
        - row_key is a string

    Ensures:
        - returns the key upper-cased with all internal whitespace removed,
          so "A-2 #2b", "A-2  #2B" and "A-2#2b" compare equal

    Raises:
        - AttributeError if row_key is not a string
    """
    return re.sub( r"\s+", "", row_key ).upper()


# ---------------------------------------------------------------------------
# S4 — THE POPULATION THIS GUARD WALKS
# ---------------------------------------------------------------------------
#
# Both languages. TypeScript was the whole population until 2026-09-19, and the
# Python parity tests were invisible to every rule in this file — not passing, not
# failing, NOT MEASURED. The guard read 19 passed with a real citation defect sitting
# in `test_multiplexer_jobs_pane_legacy_words.py`, because `.py` was outside its glob.
#
# ONE definition, used by every walker here, so a future language cannot be added to
# one loop and forgotten in another.
TEST_FILE_GLOBS = ( "src/tests/**/*.test.ts", "src/tests/**/*.py" )


def walk_test_files( project_root ):
    """Every file this guard polices, in a stable order."""
    seen = []
    for pattern in TEST_FILE_GLOBS:
        seen += sorted( project_root.glob( pattern ) )
    return seen


@pytest.fixture( scope="module" )
def project_root():
    return Path( cu.get_project_root() )


@pytest.fixture( scope="module" )
def summary_table( project_root ):
    """
    The manifest's summary table, parsed two independent ways.

    Returns ( keys, data_row_count ):
      - keys           every row key ROW_KEY could parse, normalized
      - data_row_count every data row in the table, counted WITHOUT ROW_KEY

    The two are separate on purpose. Counting rows by a pattern and then
    checking that count against the same pattern is a tautology; the row count
    here comes from the table's own shape — a pipe-delimited line that is not
    the header and not the `|---|` separator — so a key shape ROW_KEY cannot
    parse shows up as a DISAGREEMENT rather than as a silently short
    denominator. That is the defect this fixture exists to make impossible.

    Scoped to the `## Summary table` section alone. The `## Minting state`
    table above it repeats 15 of the same keys, so a whole-file parse conflates
    two populations and cannot say which one it is reporting.
    """
    text    = ( project_root / MANIFEST_REL ).read_text( encoding="utf-8" )
    lines   = text.splitlines()

    start = next( i for i, line in enumerate( lines ) if line.strip() == "## Summary table" )
    end   = next(
        ( i for i in range( start + 1, len( lines ) ) if lines[ i ].startswith( "## " ) ),
        len( lines ),
    )

    keys           = set()
    data_row_count = 0

    for line in lines[ start:end ]:
        if not line.startswith( "|" ): continue

        first_cell = line.split( "|" )[ 1 ].strip()
        if first_cell in ( "Row key", "" ) or set( first_cell ) <= set( "-: " ): continue

        data_row_count += 1

        match = MANIFEST_ROW.match( line )
        if match: keys.add( _normalize( match.group( 1 ) ) )

    return keys, data_row_count


@pytest.fixture( scope="module" )
def legacy_bodies( project_root ):
    return js_method_bodies( ( project_root / LEGACY_JS_REL ).read_text( encoding="utf-8" ) )


@pytest.fixture( scope="module" )
def legacy_spans( project_root ):
    return html_element_spans( ( project_root / LEGACY_HTML_REL ).read_text( encoding="utf-8" ) )


@pytest.fixture( scope="module" )
def legacy_script_names( project_root ):
    """Names declared in notifications.html's inline scripts — the second html population."""
    return html_inline_script_names( ( project_root / LEGACY_HTML_REL ).read_text( encoding="utf-8" ) )


@pytest.fixture( scope="module" )
def manifest_text( project_root ):
    return ( project_root / MANIFEST_REL ).read_text( encoding="utf-8" )


@pytest.fixture( scope="module" )
def manifest_row_keys( summary_table ):
    """Every row key the manifest's summary table lists, normalized."""
    keys, _ = summary_table
    return keys


@pytest.fixture( scope="module" )
def claiming_tests( project_root ):
    """
    Every test file whose header claims a parity row key.

    Returns a list of ( repo_relative_path, row_key, header_text ) — the
    declared population this guard polices.
    """
    return parity_census( project_root )[ "claims" ]


def parity_census( project_root ):
    """
    The whole declared population, split by HOW it declares.

    Ensures:
        - "claims"    — [ ( path, row_key, header ) ] a file DECLARING a row, by
                        marker or by the transitional old shape. EXEMPT files are
                        NOT here: an exemption says this file mirrors no legacy
                        passage, so the weak form has nothing to ask of it
        - "exempt"    — [ ( path, row_key, reason, header ) ]
        - "old_shape" — the subset of paths in "claims" declaring via prose, the
                        number the transitional arm is retiring
    """
    claims, exempt, old_shape = [], [], []

    for path in walk_test_files( project_root ):
        rel    = str( path.relative_to( project_root ) )
        header = "\n".join( path.read_text( encoding="utf-8" ).splitlines()[ :HEADER_LINES ] )

        marker = marker_claim( header )
        if marker is not None:
            kind, key, reason = marker
            if kind == "EXEMPT": exempt.append( ( rel, key, reason, header ) )
            else:                claims.append( ( rel, key, header ) )
            continue

        key = old_shape_claim( header )
        if key is not None:
            claims.append( ( rel, key, header ) )
            old_shape.append( rel )

    return { "claims": claims, "exempt": exempt, "old_shape": old_shape }


@pytest.fixture( scope="module" )
def exempt_tests( project_root ):
    """Files declaring PARITY-EXEMPT — they mirror no legacy passage."""
    return parity_census( project_root )[ "exempt" ]


@pytest.fixture( scope="module" )
def old_shape_tests( project_root ):
    """Files still declaring via the transitional prose shape."""
    return parity_census( project_root )[ "old_shape" ]


# ---------------------------------------------------------------------------
# The denominator — asserted before anything is asserted about the tests.
# A loop over nothing passes every assertion inside it.
# ---------------------------------------------------------------------------

def test_the_manifest_is_readable_and_lists_its_rows( manifest_row_keys ):
    """Without the manifest there is no declared population, only a corpus."""
    assert len( manifest_row_keys ) >= 40, (
        f"the manifest's summary table parsed to {len( manifest_row_keys )} row keys; "
        f"44 were counted on 2026-09-17. A parse that collapses to a handful means the "
        f"table's shape changed and this guard is now policing a denominator it invented"
    )


def test_the_denominator_accounts_for_every_row_in_the_table( summary_table ):
    """
    ROW_KEY parses every data row the summary table has — no silent shortfall.

    This is the assertion whose absence let the denominator read 42 against a
    table of 44: `B-1b` and `B-5L` were unparseable, and a floor check cannot
    see a key it never parsed. The floor above answers "did the parse collapse";
    only this answers "did the parse account for everything".

    The two sides reach the same number by different routes — one by matching
    row keys, one by counting table rows — so they can actually disagree.
    """
    keys, data_row_count = summary_table

    assert len( keys ) == data_row_count, (
        f"the summary table has {data_row_count} data rows but ROW_KEY parsed only "
        f"{len( keys )} of them. A row key whose shape ROW_KEY cannot read is invisible "
        f"to this guard's denominator, and any test claiming it would be reported as "
        f"claiming a row the manifest does not list. Widen ROW_KEY to the shape actually "
        f"in the table — and widen it as a PREDICATE, not by adding another alternative"
    )


def test_at_least_one_test_claims_a_row( claiming_tests ):
    """
    The guard must be able to find a positive before a zero means anything.

    Nine files claimed a row on 2026-09-17. A drop to zero means the header
    convention changed and every assertion below is passing vacuously.
    """
    assert claiming_tests, (
        "no test file claims a parity row key in its header — either the convention "
        "changed or this guard's recogniser is broken. Either way it is now policing "
        "an empty set and cannot fail"
    )


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------

def test_every_claimed_row_key_is_one_the_manifest_lists( claiming_tests, manifest_row_keys ):
    """A test claiming a row that does not exist is pointing at nothing."""
    unknown = [
        ( path, key ) for path, key, _ in claiming_tests
        if _normalize( key ) not in manifest_row_keys
    ]

    assert not unknown, (
        "these tests claim a parity row key the manifest does not list — a typo, or a "
        "row key that was retired without sweeping the tests that vouch for it:\n  "
        + "\n  ".join( f"{path} claims {key!r}" for path, key in unknown )
    )


def test_a_parity_test_names_the_legacy_source_it_mirrors(
    claiming_tests, legacy_bodies, legacy_spans, legacy_script_names
):
    """
    Build plan §6 item 19, weak form: if a test claims a build-item row, its header
    names the legacy passage it mirrors — as a `file:line` coordinate OR as a symbol
    that resolves exactly once.

    🔴 "SYMBOL" IS NOT js-ONLY, and reading it that way is the mistake this paragraph
    exists to prevent (Mr. Radio, 2026-09-27). Three populations satisfy this rule:
    a `notifications.js` method, a `notifications.html` ELEMENT ID written `#the-id`, and
    a name declared in one of notifications.html's INLINE `<script>` blocks, written bare.
    The third is the surprising one and it is load-bearing: four parity tests mirror
    `LUPIN_ACCORDION_PERSIST_KEYS`, `toggleSection` and `applyPersistedAccordions`, which
    live in the markup file and are not elements, so before this rule they had no honest
    citation at all.

    🔴 THE SYMBOL FORM IS THE PREFERRED ONE, and this guard used to forbid it.
    The manifest's standing rule 1 (Mr. Radio 🦉, 2026-09-19) reads "cite the anchor text
    and the symbol, NEVER the line number", and seven files obeyed it — naming the rule in
    their own headers — while this assertion scored them as defects for doing so. Ruled
    2026-09-27: a symbol satisfies the rule, WITH a uniqueness condition, because a name
    that resolves twice is no more a coordinate than a line number that resolves nowhere.

    Not an argument, a measurement: all 45 defects reported by
    `test_a_parity_citation_resolves_inside_what_it_names` at 7db04b8af are rotted LINE
    numbers. None is a rotted symbol.

    Exemplar of the coordinate form: `render/scroll_reveal.test.ts`. ⚠️ Copy its SHAPE and
    not its numbers — its own citation is one of the 45.

    A PARITY-EXEMPT file is not in `claiming_tests` at all — an exemption is the
    statement that this file mirrors no legacy passage, so there is no coordinate
    for it to be missing. `test_an_exempt_file_carrying_a_legacy_coordinate_is_red`
    is what stops that from becoming a way to opt out of the rule.
    """
    offenders = []
    for path, key, header in claiming_tests:
        if path in GRANDFATHERED or LEGACY_COORD.search( header ): continue
        js_ok,   js_defects   = symbol_citation_defects( header, legacy_bodies )
        html_ok, html_defects = html_symbol_citation_defects(
            header, legacy_spans, legacy_script_names )
        if js_ok or html_ok: continue
        offenders.append( ( path, key, js_defects + html_defects ) )

    assert not offenders, (
        "these tests claim a parity row but do not name the legacy passage they mirror "
        f"in their first {HEADER_LINES} lines (build plan §6 item 19). ANY of these forms "
        "is accepted, and the first three are the ones standing rule 1 asks for, because a "
        "symbol survives an edit above it and a line number does not:\n"
        "  • a method that resolves EXACTLY ONCE — `notifications.js  someMethod`;\n"
        "  • an element id that resolves EXACTLY ONCE — `notifications.html  #the-id`;\n"
        "  • a name declared EXACTLY ONCE in one of notifications.html's inline <script> "
        "blocks, written without the `#` — `notifications.html  toggleSection`. This "
        "population is easy to miss: the markup file holds real code, and a citation of it "
        "is neither a method in notifications.js nor an element;\n"
        "  • a `notifications.js:NNN` / `notifications.html:NNN-NNN` coordinate.\n"
        "A name resolving twice is NOT accepted, in any population: it names neither.\n  "
        + "\n  ".join(
            f"{path} claims {key!r}"
            + ( "" if not defects else " — " + "; ".join( f"{n}: {why}" for n, why in defects ) )
            for path, key, defects in offenders
        )
    )


# ---------------------------------------------------------------------------
# S1 — the marker, the exemption, and the self-retiring transitional arm
# ---------------------------------------------------------------------------

def test_a_mention_is_not_a_claim( project_root ):
    """
    The two live shapes that MENTION a row without declaring one stay out.

    Both are pinned here as committed fixtures rather than described in prose:
    delete `is_table_row` or `is_inside_quotes` and THIS test names the shape that
    walked back in. They are the entire evidence base for the transitional arm, and
    an arm fitted to two examples has to keep those two examples where a deletion
    trips over them.

    Their real line numbers are given so a reader can go and look, but the assertion
    does NOT depend on them — a coordinate goes stale, and the shape is the point.
    """
    table_row = (
        "//     mux     HoldingAreaStore   patchTask           "
        "PATCH /api/tasks/{id}      (parity A-2 #0)"
    )   # notifications_js/both_clients_issue_the_same_request_for_every_control.test.ts
    docstring = (
        '("Parity A-0", "parity A-2 #2b"), and the row key must be one the manifest'
    )   # this file's own header, explaining its own format

    # Control FIRST: the recogniser DOES see a claim in both, so the rejection below
    # is the filters working and not the regex failing to match.
    assert CLAIMS_A_ROW.search( table_row ) is not None
    assert CLAIMS_A_ROW.search( docstring ) is not None

    assert old_shape_claim( table_row ) is None, (
        "a TABLE ROW mentioning a row key is being read as a claim — `is_table_row` "
        "is gone or broken. That file carries no legacy coordinate anywhere, so it "
        "would be reported as an offender for a row it never claimed"
    )
    assert old_shape_claim( docstring ) is None, (
        "a DOCSTRING EXAMPLE is being read as a claim — `is_inside_quotes` is gone or "
        "broken. The example above is this guard's own, so the guard would police itself"
    )

    # And ordinary prose still declares, or the transitional arm has eaten the corpus.
    assert old_shape_claim( " * Parity A-2 #2h — the card's keyboard." ) == "A-2 #2h"


def test_the_marker_is_recognised_and_survives_a_wide_window():
    """
    A marker is defined by PLACEMENT, which is what makes it window-proof.

    The two negatives above are admitted by every header-window variant Maya
    measured. Neither can be written as a marker, because a marker is the first
    content on its line.
    """
    assert marker_claim( "// PARITY-CLAIM: A-2 #10" )    == ( "CLAIM", "A-2 #10", "" )
    assert marker_claim( "# PARITY-CLAIM: A-2 #10" )     == ( "CLAIM", "A-2 #10", "" )
    assert marker_claim( " * PARITY-CLAIM: B-5L" )       == ( "CLAIM", "B-5L", "" )
    assert marker_claim( "PARITY-CLAIM: A-0" )           == ( "CLAIM", "A-0", "" )

    # The negatives cannot become markers: both have content before the claim.
    assert marker_claim( "//  mux  patchTask  (parity A-2 #0)" ) is None
    assert marker_claim( '("Parity A-0", "parity A-2 #2b"), and the row key' ) is None

    # A marker mentioned mid-sentence is prose about a marker, not a marker.
    assert marker_claim( "the file writes PARITY-CLAIM: A-2 #10 in its header" ) is None


def test_an_exemption_without_a_reason_is_refused():
    """
    Precedent: stylelint refuses a waiver with no same-line reason
    (`.stylelintrc.json:3`, `run-stylelint-gate.sh:85`).

    An exemption removes a file from the rule. The reason is the only thing that
    makes that auditable later, so it is not optional.
    """
    kind, key, reason = marker_claim( "# PARITY-EXEMPT: A-2 #2a — happy-dom has no cascade" )
    assert ( kind, key ) == ( "EXEMPT", "A-2 #2a" )
    assert reason == "happy-dom has no cascade"

    for reasonless in [ "# PARITY-EXEMPT: A-2 #2a",
                        "# PARITY-EXEMPT: A-2 #2a —",
                        "# PARITY-EXEMPT: A-2 #2a — " ]:
        assert marker_claim( reasonless )[ 2 ] == "", (
            f"{reasonless!r} produced a reason out of nothing"
        )


def test_every_declared_exemption_states_a_reason( exempt_tests ):
    """The live rule over the live corpus — the unit test above is its instrument."""
    reasonless = [ ( path, key ) for path, key, reason, _ in exempt_tests if not reason ]

    assert not reasonless, (
        "these files declare PARITY-EXEMPT with no reason on the marker line. An "
        "exemption that does not say why cannot be audited or retired — write "
        "`PARITY-EXEMPT: <row> — <why this file mirrors no legacy passage>`:\n  "
        + "\n  ".join( f"{path} exempts {key!r}" for path, key in reasonless )
    )


def test_rot_detection_fires_on_an_exemption_that_has_gone_stale():
    """
    🔴 THE INSTRUMENT FOR THE RULE BELOW, AND IT DOES NOT DEPEND ON THE CORPUS.

    WHY IT EXISTS, since the reason is no longer visible in the tree: before S4 this
    guard's glob was `.test.ts` only, the single exempt file was Python, so
    `exempt_tests` was EMPTY and the corpus rule below passed however broken it was.
    Mutation found it — breaking the exemption so a coordinate rode with it killed no
    test at all. S4 widened the glob and the corpus rule now has a file to police.

    ⚠️ DO NOT DELETE THIS AS REDUNDANT NOW THAT THE CORPUS IS NON-EMPTY. It holds the
    rule against a population of ZERO, which is one deleted exemption away and would
    take the corpus rule back to silently passing. That is the state it was written
    in, and the state it prevents returning to.
    """
    clean   = "# PARITY-EXEMPT: A-2 #2a — happy-dom has no cascade"
    rotted  = clean + "\nand it mirrors notifications.js:25892-25947"

    assert exemption_has_rotted( clean ) is False, "a clean exemption must not be flagged"
    assert exemption_has_rotted( rotted ) is True, (
        "an exempt file carrying a legacy coordinate is not being flagged. The "
        "exemption says the file mirrors no legacy passage; a coordinate says it does. "
        "Nothing else can catch this — an exemption removes the file from every other "
        "assertion in this guard"
    )

    # A NON-exempt header with a coordinate is ordinary and must never be flagged.
    assert exemption_has_rotted( "# PARITY-CLAIM: A-2 #10\nnotifications.js:5735" ) is False


def test_an_exempt_file_carrying_a_legacy_coordinate_is_red( exempt_tests ):
    """
    ROT DETECTION over the live corpus. An exemption is a claim about CONTENT,
    and content changes.

    Live since S4 widened the glob to `.py`: it polices the one exempt file in the
    tree, which is Python. Before that it was a loop over an empty list.

    ⚠️ IT GOES VACUOUS AGAIN THE MOMENT THE LAST EXEMPTION IS DELETED, and passes
    silently when it does. `test_rot_detection_fires_on_an_exemption_that_has_gone_stale`
    is the one that holds the rule in that state — do not read a green here as
    evidence on its own.
    """
    rotted = [
        ( path, key, LEGACY_COORD.search( header ).group( 0 ) )
        for path, key, _, header in exempt_tests
        if exemption_has_rotted( header )
    ]

    assert not rotted, (
        "these files declare PARITY-EXEMPT — 'mirrors no legacy passage' — and then "
        "name a legacy coordinate. The exemption is stale: either drop it and let the "
        "citation rules apply, or remove the coordinate:\n  "
        + "\n  ".join( f"{path} exempts {key!r} but cites {coord}" for path, key, coord in rotted )
    )


def exemption_has_a_fallback( header ):
    """
    Whether an EXEMPT file would still be found if its marker stopped parsing.

    Requires:
        - header is the file's leading lines

    Ensures:
        - True when the row key also appears, in prose, on a line of the header
          window that is NOT the marker line
        - True for a header with no EXEMPT marker — the question does not apply

    WHY THIS IS THE RIGHT TEST AND A LINE COUNT IS NOT. Removing the marker line
    shifts everything below it UP, never down, so a row key already inside the
    window stays inside it. A mention on any other header line is therefore a
    genuine second thread, whatever the marker's length.
    """
    marker = marker_claim( header )
    if marker is None or marker[ 0 ] != "EXEMPT": return True

    for line in header.splitlines():
        if PARITY_MARKER.match( line ): continue
        if CLAIMS_A_ROW.search( line ): return True
    return False


def test_an_exemption_is_not_the_only_thread_holding_a_file_in_the_census():
    """
    🔴 MEMBERSHIP IS NOT REDUNDANCY — Maya 🌻's catch, 2026-09-19.

    The near-miss detector reports a typo'd marker. It cannot report a marker that
    was DELETED, and it is one predicate: if it is ever narrowed, the file it was
    protecting goes quiet again. A file whose ONLY route into the census is its
    marker line has one line of margin and no second thread.

    So an exemption must sit ON a file that the old recogniser can still see. Then a
    broken marker costs a red from the near-miss detector AND leaves the file in
    `claims`, where the weak form asks it for a citation. Two independent routes.

    Measured on this tree: the one exempt file's prose claim sat at line 13 against a
    12-line window — ONE line outside — so the marker was its only thread.
    """
    no_fallback = (
        '"""\n'
        "PARITY-EXEMPT: A-2 #2a — mirrors no legacy passage\n"
        "\n"
        "Some prose that never names the row again.\n"
    )
    assert exemption_has_a_fallback( no_fallback ) is False, (
        "an exemption whose file names its row NOWHERE else in the header window has "
        "a single point of failure: break the marker and the file leaves both censuses"
    )

    with_fallback = no_fallback + "Found building parity A-2 #2a (2026-09-16).\n"
    assert exemption_has_a_fallback( with_fallback ) is True

    # A file with no exemption is not asked the question.
    assert exemption_has_a_fallback( "// Parity A-2 #5 — the dial." ) is True


def test_every_exempt_file_keeps_a_second_thread( exempt_tests ):
    """
    The live rule, over the one exempt file S4 brought into the population.

    The test above is its instrument and holds the rule when this list is empty —
    which it was before S4, and will be again if the last exemption is deleted.
    """
    lonely = [
        ( path, key ) for path, key, _, header in exempt_tests
        if not exemption_has_a_fallback( header )
    ]

    assert not lonely, (
        "these files are held in the census by their PARITY-EXEMPT marker ALONE. Name "
        f"the row in prose somewhere else in the first {HEADER_LINES} lines too, so a "
        "broken marker leaves the file in `claims` instead of removing it from every "
        "population this guard measures:\n  "
        + "\n  ".join( f"{path} exempts {key!r}" for path, key in lonely )
    )


def test_a_near_miss_marker_is_refused_rather_than_ignored():
    """
    🔴 THE FAILURE MODE A CENSUS CANNOT SEE: a file in NEITHER population.

    A well-formed marker puts a file in `exempt`. A missing marker leaves it in
    `claims` via the transitional arm. A MISTYPED one can do neither — the attempt
    itself pushes the file's prose claim past the header window, so the file leaves
    the declared population and nothing reddens. Both counts stay plausible.

    Maya 🌻 hit this from the other side on 2026-09-19: her first probe of this tree
    read exempt=0 and she was about to file it as a silent exclusion. She was looking
    at the right hazard.
    """
    good = "# " + "PARITY-EXEMPT" + ": A-2 #2a — happy-dom has no cascade"
    assert marker_claim( good ) is not None
    assert marker_near_miss( good ) is False, "a well-formed marker is not a near miss"

    for typo in [ "# " + "PARITY-EXEMPTED" + ": A-2 #2a — reason",
                  "# " + "PARITY EXEMPT"   + ": A-2 #2a — reason",
                  "# " + "PARITY-EXEMPT"   + " A-2 #2a — reason",
                  "#   text before " + "PARITY-CLAIM" + ": A-2 #10" ]:
        assert marker_claim( typo ) is None, f"{typo!r} should not parse as a marker"
        assert marker_near_miss( typo ) is True, (
            f"{typo!r} reaches for a marker and misses, and is being SILENTLY IGNORED. "
            "A file doing this leaves the declared population entirely — it lands in "
            "neither `claims` nor `exempt`, and no count here looks wrong"
        )

    # A header that never reached for a marker is not a near miss.
    assert marker_near_miss( " * Parity A-2 #2h — the card's keyboard." ) is False

    # 🔴 AND ORDINARY PROSE IS NOT AN ATTEMPT. This exact sentence is live in
    # `render/fleet_size_cap_dial_parity.test.ts`, and the first cut of the detector
    # accused it. Pinned here so a return to a case-insensitive predicate reddens.
    assert marker_near_miss(
        "// Store behaviour and renderer behaviour are both here, because the parity claim is\n"
        "// the pair: a store that saves correctly behind a dial that never disables is not it."
    ) is False, "ordinary prose using the words 'parity claim' is not a marker attempt"


def test_no_file_reaches_for_a_marker_and_misses( project_root ):
    """The live rule. `test_a_near_miss_marker_is_refused_rather_than_ignored` is its instrument."""
    missed = []
    for path in walk_test_files( project_root ):
        header = "\n".join( path.read_text( encoding="utf-8" ).splitlines()[ :HEADER_LINES ] )
        if marker_near_miss( header ):
            missed.append( str( path.relative_to( project_root ) ) )

    assert not missed, (
        "these headers contain something marker-SHAPED that this guard does not "
        "recognise as a marker. A near miss is worse than no marker at all: the file "
        "drops out of `claims` AND `exempt` and no count looks wrong. Write exactly "
        "`PARITY-CLAIM: <row>` or `PARITY-EXEMPT: <row> — <why>`, as the first content "
        "on its line:\n  " + "\n  ".join( missed )
    )


def test_the_declared_population_is_exactly_what_was_pinned( claiming_tests, exempt_tests ):
    """
    🔴 THE TWO DIRECTIONS MEAN DIFFERENT THINGS AND ARE REPORTED DIFFERENTLY.

    A DEPARTURE is the regression this pin exists to catch: a file that declared a
    parity row and no longer does. It left `claims` and `exempt` both, so every other
    rule in this file silently stopped asking it anything. That is a recogniser
    change, a header edit, a rename or a deletion — and it must be read, not bumped.

    An ARRIVAL is ordinary growth. It is still red, because a pin that only checks one
    direction trails the population it guards, and a trailing pin is satisfied by
    exactly the regression it was written for. But the action is to add the line.

    `test_at_least_one_test_claims_a_row` remains the vacuity floor beneath this.
    """
    live     = { p for p, _, _ in claiming_tests } | { p for p, _, _, _ in exempt_tests }
    departed = sorted( DECLARED_POPULATION - live )
    arrived  = sorted( live - DECLARED_POPULATION )

    assert not departed, (
        "these files were declaring a parity row at the pinned sha and are NOT "
        "declaring one now. A departure removes a file from EVERY rule in this guard "
        "at once, and nothing else reports it. Read each one before touching the pin "
        "— a recogniser change, a header edit above the window, a rename, a deletion:"
        "\n  " + "\n  ".join( departed )
    )

    assert not arrived, (
        "these files declare a parity row and are not in DECLARED_POPULATION. This is "
        "ordinary growth — add them to the pin in the same commit that adds them, so "
        "the pin never trails the population it guards:\n  " + "\n  ".join( arrived )
    )


def test_the_old_shape_count_only_shrinks( old_shape_tests ):
    """
    The transitional arm is SELF-RETIRING, on the `GRANDFATHERED` pattern.

    `is_table_row` and `is_inside_quotes` are a proxy fitted to two known negatives.
    A proxy with no denominator is tolerable only while its blast radius is a number
    someone is watching go to zero. This is that number.

    When it reaches zero, delete both filters, `old_shape_claim`, this test and the
    TRANSITIONAL ARM comment together.
    """
    assert len( old_shape_tests ) <= OLD_SHAPE_CEILING, (
        f"{len( old_shape_tests )} files declare a parity row in the old prose shape, "
        f"above the ceiling of {OLD_SHAPE_CEILING}. A NEW file must use "
        "`PARITY-CLAIM: <row>`. The prose shape is being retired, so this count may "
        "only go down:\n  " + "\n  ".join( sorted( old_shape_tests ) )
    )


# ---------------------------------------------------------------------------
# The grandfather list is a ceiling, not a floor
# ---------------------------------------------------------------------------

def test_the_grandfather_list_only_shrinks( claiming_tests ):
    """
    An entry that no longer violates must leave the list.

    Without this, the list is a place debt goes to be forgotten: a file could be
    fixed and still sit here, and the next reader would take the length of the
    list for the size of the debt. Here it can only shrink.
    """
    claimed_paths = { path for path, _, _ in claiming_tests }

    still_clean = sorted(
        path for path, _, header in claiming_tests
        if path in GRANDFATHERED and LEGACY_COORD.search( header )
    )
    assert not still_clean, (
        "these files now name their legacy source and must be removed from "
        "GRANDFATHERED — the list records debt that is already paid:\n  "
        + "\n  ".join( still_clean )
    )

    departed = sorted( GRANDFATHERED - claimed_paths )
    assert not departed, (
        "GRANDFATHERED names files that no longer claim a parity row — deleted, renamed, "
        "or their header changed. Remove them; a stale entry silently exempts a path that "
        "may come back:\n  " + "\n  ".join( departed )
    )


# ---------------------------------------------------------------------------
# The strong form — a citation RESOLVES at HEAD, inside what it names
# ---------------------------------------------------------------------------

def test_the_legacy_parsers_find_what_they_claim( legacy_bodies, legacy_spans ):
    """
    Positive controls for the two instruments, before either is trusted.

    A parser that finds nothing makes every citation "name no method" — red, but
    for the wrong reason. These pin one known method and one known element, and
    the order of their bounds, so a broken parse is reported as a broken parse.
    """
    assert len( legacy_bodies ) > 500, f"only {len( legacy_bodies )} legacy methods parsed"
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    assert start < end, "onTTSPlaybackComplete's body closes before it opens"

    assert "tts-queue-section" in legacy_spans, "the html parse found no #tts-queue-section"
    ( open_line, close_line ), = legacy_spans[ "tts-queue-section" ]
    assert open_line < close_line, "#tts-queue-section closes on the line it opens"
    assert all( open_line < a and b < close_line for a, b in legacy_spans[ "tts-pause-btn" ] ), (
        "#tts-pause-btn is not nested inside #tts-queue-section — the close-tag match is wrong"
    )


# ---------------------------------------------------------------------------
# The html symbol rule — element ids AND inline-script names
# ---------------------------------------------------------------------------
#
# Ruled 2026-09-27 (Mr. Radio 🦉). Every case below drives the REAL notifications.html
# except the one that says otherwise in its own name, and that exception is explained where
# it sits rather than here.

# ---------------------------------------------------------------------------
# CONDITION 3 — the mutation evidence for the html symbol rule, and HOW TO RE-DERIVE IT
# ---------------------------------------------------------------------------
#
# Mr. Radio required one arm per citation FORM, each naming the test that reddens, with the
# sha256 read back. Recorded here rather than only in a commit message, because a commit
# message is read once and this file is read whenever someone doubts the rule.
#
# 🔴 RIO'S CONSTRAINT, AND IT FOLLOWS FROM A MEASUREMENT RATHER THAN A PREFERENCE: an arm
# must be SITED on a header satisfying exactly ONE form. Satisfaction is decided per FILE,
# not per citation, so breaking every element id in `tts_pause_play_parity` left it green —
# its js symbol carries the header alone. A multi-form site survives BY CONSTRUCTION, and a
# survivor then reads as a gap in the guard instead of as a badly-placed probe.
#
# Measured 2026-09-27 at 814051e0b, in a DETACHED worktree (the seat's tree had a live unit
# tier in it, and a run whose tree moves is unfalsifiable, not merely stale). Baseline
# failing set was EMPTY before every arm and EMPTY after every restore.
#
#   form                site — satisfies exactly        anchors  killed by
#   js symbol           debug_sink_parity  {js}               4  resolves_inside + names_the_legacy_source
#   html #id            flow_ratio_model_and_banner {#id}     3  both
#   inline-script name  section_collapse_persist {script}     3  both
#   planted coordinate  scroll_reveal                        1  resolves_inside
#
#   sha before → mutated → restored (all restored OK)
#   2db2261d46aaa867 → a0a4f6502bf0095a → 2db2261d46aaa867
#   119d2e08dea385cd → 5f67495cb39de34d → 119d2e08dea385cd
#   1795f537f069bc7d → 763a04d6ebca658a → 1795f537f069bc7d
#   71406f38ec7123eb → bdf6c3ed8d64daaa → 71406f38ec7123eb
#
# ⚠️ THE COORDINATE ARM IS CONSTRUCTED AND IS LABELLED SO. Zero of the fifty claiming
# headers carry a line coordinate now, so no real header can supply that arm — it plants
# `notifications.js:99000-99001`. A green there says the checker can still say no; it says
# nothing about the tree.
#
# RE-DERIVING, without the scratch harness, which does not outlive the session. Isolate the
# three forms by feeding the guard's OWN predicates a restricted table — no re-statement of
# its rules — and refuse to write unless the site is single-form:
#
#   forms( header ) = {
#     "js symbol"         : symbol_citation_defects( header, bodies )[ 0 ],
#     "html #id"          : html_symbol_citation_defects( header, spans, {} )[ 0 ],
#     "inline-script name": html_symbol_citation_defects( header, {}, script_names )[ 0 ],
#     "coordinate"        : bool( LEGACY_COORD.search( header ) ),
#   }
#
# Then per arm: assert the site's live form set equals the one under test; break EVERY
# citation of that form in the file (one is masked by a sibling — "one good citation is
# enough"); read the sha before and after and assert it moved; run this module and record
# the NAMED failing tests; restore and read the sha back.

def test_the_inline_script_parser_finds_what_it_claims( legacy_script_names ):
    """
    Positive control for the third instrument, before it is trusted.

    A parser that finds nothing makes every inline-script citation "no such name" — red
    for the wrong reason, and indistinguishable from a citation that is genuinely wrong.
    It also pins the two properties the rule depends on: a CALL is not a declaration, and
    a name declared twice is recorded twice.
    """
    assert legacy_script_names, "the inline-script parse found nothing at all"
    for name in ( "LUPIN_ACCORDION_PERSIST_KEYS", "toggleSection", "applyPersistedAccordions" ):
        assert len( legacy_script_names.get( name, [] ) ) == 1, (
            f"{name} should be declared exactly once; parsed "
            f"{legacy_script_names.get( name )}" )

    assert legacy_script_names[ "toggleSection" ][ 0 ] < \
           legacy_script_names[ "applyPersistedAccordions" ][ 0 ], \
        "the two are recorded out of file order — the line arithmetic is wrong"

    # 🔴 A DECLARATION MID-LINE IS NOT A DECLARATION OF THIS FILE'S VOCABULARY, and this is
    # the assertion that makes the pattern's line anchor load-bearing. The scripts contain
    # `for (const sectionId in LUPIN_ACCORDION_PERSIST_KEYS)` — a loop binding, not a name
    # any header should be able to cite. Drop `^[ \t]*` from the const alternative and
    # `sectionId` joins the population; nothing else in this file would have noticed.
    #
    # ⚠️ Measured 2026-09-27 while mutation-testing this rule: the FUNCTION half of that
    # pattern cannot be tested the same way, because the scripts hold zero mid-line
    # `function NAME` occurrences — dropping its anchor is an EQUIVALENT mutant against the
    # real file, and no assertion here can kill it. That is a property of the fixture, not
    # a gap in this test, and it is recorded rather than papered over.
    assert "sectionId" not in legacy_script_names, (
        "`sectionId` is a loop binding inside `for (const sectionId in …)`, not a citable "
        f"declaration — the pattern's line anchor is gone. Parsed: "
        f"{legacy_script_names.get( 'sectionId' )}" )


def test_a_unique_element_id_is_a_citation( legacy_spans, legacy_script_names ):
    """The form the rule exists to accept, in both shapes the tree writes."""
    for header in (
        "// mirrors notifications.html  #tts-queue-section",
        "// mirrors `#tts-queue-section` in notifications.html",
    ):
        satisfied, defects = html_symbol_citation_defects(
            header, legacy_spans, legacy_script_names )
        assert satisfied, f"{header!r} was rejected: {defects}"


def test_a_unique_inline_script_name_is_a_citation( legacy_spans, legacy_script_names ):
    """
    The population a reader does not expect, so it is pinned in both shapes too.

    Written WITHOUT the `#`, which is the whole discriminator: `#toggleSection` would be
    looked up among element ids and found nowhere.
    """
    for header in (
        "// mirrors notifications.html  toggleSection",
        "// mirrors `toggleSection`, in notifications.html",
    ):
        satisfied, defects = html_symbol_citation_defects(
            header, legacy_spans, legacy_script_names )
        assert satisfied, f"{header!r} was rejected: {defects}"


def test_an_unknown_element_id_is_not_a_citation( legacy_spans, legacy_script_names ):
    """Absent and duplicated are DIFFERENT defects; this pins the absent one's reason."""
    satisfied, defects = html_symbol_citation_defects(
        "// mirrors notifications.html  #no-such-element-anywhere",
        legacy_spans, legacy_script_names )

    assert not satisfied
    assert defects == [ ( "no-such-element-anywhere", "no such element id in notifications.html" ) ], \
        f"the reason must name the population it searched: {defects}"


def test_an_unknown_inline_script_name_is_not_a_citation( legacy_spans, legacy_script_names ):
    """The same, for the other population, with a reason that says which one it searched."""
    satisfied, defects = html_symbol_citation_defects(
        "// mirrors notifications.html  noSuchFunctionAnywhere",
        legacy_spans, legacy_script_names )

    assert not satisfied
    assert defects == [ ( "noSuchFunctionAnywhere", "no such inline-script name in notifications.html" ) ], \
        f"the reason must name the population it searched: {defects}"


def test_a_duplicated_inline_script_name_is_not_a_citation( legacy_spans, legacy_script_names ):
    """
    A REAL duplicate, from the shipped file — `content` is declared twice inside the
    accordion scripts.

    This arm is deliberately not a constructed fixture. Mr. Radio ruled on 2026-09-27 that
    the duplicate case use the real file where the real file can supply one, and it can
    here: the same rule's element-id half CANNOT, because all of notifications.html's ids
    are unique today (see the case below, which says so in its name).
    """
    assert len( legacy_script_names.get( "content", [] ) ) > 1, (
        "`content` is no longer declared twice in notifications.html's inline scripts — "
        "this case needs a new real duplicate, or it is testing nothing. Parsed: "
        f"{legacy_script_names.get( 'content' )}" )

    satisfied, defects = html_symbol_citation_defects(
        "// mirrors notifications.html  content", legacy_spans, legacy_script_names )

    assert not satisfied, "a name declared twice was accepted as a citation"
    ( name, why ), = defects
    assert name == "content"
    assert "declared 2 times" in why and "resolves twice names neither" in why, \
        f"the reason must distinguish duplicated from absent: {why!r}"
    assert "inline-script name" in why, f"the reason must name the population: {why!r}"


def test_a_duplicated_element_id_is_not_a_citation_constructed( legacy_script_names ):
    """
    The element-id duplicate arm, on a CONSTRUCTED table — and it says so in its name.

    ⚠️ THIS IS NOT A FIXTURE FROM REALITY, and a green here is no statement about the
    markup. All 252 ids in notifications.html are unique (measured 2026-09-27), so the
    branch is unreachable from the real file and there is nothing honest to drive it with.
    The arm exists because a duplicate id is possible in HTML and would be a real defect;
    it is kept beside the real-duplicate case above so a reader can see which evidence is
    which.
    """
    spans = { "twice-over": [ ( 10, 20 ), ( 30, 40 ) ] }

    satisfied, defects = html_symbol_citation_defects(
        "// mirrors notifications.html  #twice-over", spans, legacy_script_names )

    assert not satisfied
    ( name, why ), = defects
    assert name == "twice-over"
    assert "declared 2 times (10-20; 30-40)" in why, f"the reason must show both spans: {why!r}"
    assert "element id" in why, f"the reason must name the population: {why!r}"


def test_a_header_citing_no_html_symbol_reports_no_defect( legacy_spans, legacy_script_names ):
    """
    Nothing cited is NOT the same as something cited wrongly.

    The naming test asks js and html in turn and joins their defect lists, so an html
    reading of a js-only header must contribute NOTHING — otherwise every js citation would
    drag an html complaint along behind it.
    """
    satisfied, defects = html_symbol_citation_defects(
        "// mirrors notifications.js  onTTSPlaybackComplete", legacy_spans, legacy_script_names )

    assert ( satisfied, defects ) == ( False, [] ), \
        f"a js-only header produced an html defect: {defects}"


def test_the_hash_is_what_picks_the_population( legacy_spans, legacy_script_names ):
    """
    The discriminator, asserted in both directions on names that really exist.

    `tts-queue-section` is a real element and `toggleSection` a real script name; swap the
    `#` and each must be looked up in the population it does not belong to and fail there.
    Without this, a single merged table would pass every other case in this file.
    """
    wrong_way = html_symbol_citation_defects(
        "// mirrors notifications.html  tts-queue-section", legacy_spans, legacy_script_names )
    assert wrong_way == ( False, [ ( "tts-queue-section",
                                     "no such inline-script name in notifications.html" ) ] ), \
        f"a bare element id was not looked up among script names: {wrong_way}"

    other_way = html_symbol_citation_defects(
        "// mirrors notifications.html  #toggleSection", legacy_spans, legacy_script_names )
    assert other_way == ( False, [ ( "toggleSection",
                                     "no such element id in notifications.html" ) ] ), \
        f"a #-prefixed script name was not looked up among element ids: {other_way}"


def test_a_parity_citation_resolves_inside_what_it_names(
    claiming_tests, exempt_tests, legacy_bodies, legacy_spans, legacy_script_names,
    manifest_text, project_root
):
    """
    Build plan §6 item 19, STRONG form. See the module docstring for the rule.

    🔴 THE DENOMINATOR IS THE WHOLE CLAIMING POPULATION, NOT THE COORDINATE-BEARING SLICE
    OF IT (Mr. Radio, 2026-09-27). This test used to open `assert cited` over the files
    carrying a `file:line` coordinate, which was the right guard while that was the only
    accepted citation. It stopped being right the moment the symbol form landed: converting
    the last three headers off line numbers emptied that slice, and the tripwire written to
    catch "nothing is being checked" fired ON SUCCESS instead — the rule being fully obeyed
    read exactly like the guard being disconnected.

    So the population asserted here is every claiming file, each checked by the form ITS
    header uses, and the count is pinned to `DECLARED_POPULATION` so a file cannot leave the
    census silently and take its citations with it. A coordinate slice of zero is then a
    legitimate state; a claiming file that nothing checks is not.
    """
    note_dir = project_root / PHASE2_DIR_REL

    assert claiming_tests, "no test claims a parity row — every assertion below would loop over nothing"

    # ⚠️ DERIVED FROM THE PIN, NOT A SECOND COPY OF IT. `DECLARED_POPULATION` pins claims
    # AND exemptions together, so the population THIS test walks is the pin minus the
    # declared exemptions. Restating "the count is 51" here would be two artifacts encoding
    # one rule, which agree until they do not — and the off-by-one would have been mine:
    # the first cut of this assertion compared 50 claims against a 51-file pin.
    walked = { path for path, _, _ in claiming_tests }
    assert walked == DECLARED_POPULATION - { path for path, _, _, _ in exempt_tests }, (
        f"the {len( walked )} files this test walks are not the pinned population minus its "
        "exemptions. A file that drops out of the census takes its citations with it and "
        "this test goes QUIET rather than red — see "
        "test_the_declared_population_is_exactly_what_was_pinned for the set difference." )

    # Every claiming file must be checked by SOMETHING. A header carrying a coordinate is
    # checked by `unresolved_citations` below; one citing by symbol is checked by
    # `test_a_parity_test_names_the_legacy_source_it_mirrors`, which holds the uniqueness
    # condition. GRANDFATHERED files are the recorded exception and are named as such.
    unchecked = sorted(
        path for path, key, header in claiming_tests
        if path not in GRANDFATHERED
        and not LEGACY_COORD.search( header )
        and not symbol_citation_defects( header, legacy_bodies )[ 0 ]
        and not html_symbol_citation_defects( header, legacy_spans, legacy_script_names )[ 0 ] )
    assert not unchecked, (
        "these claiming files are checked by NOTHING — no coordinate for this test to "
        "resolve and no symbol for the naming test to hold to a uniqueness condition:\n  "
        + "\n  ".join( unchecked ) )

    cited = [ t for t in claiming_tests if LEGACY_COORD.search( t[ 2 ] ) ]

    offenders = [
        ( path, key, cite, reason )
        for path, key, header in cited
        for cite, reason in unresolved_citations(
            header, legacy_bodies, legacy_spans, row_notes( manifest_text, key, note_dir ) )
    ]

    # 🔴 REPORT THE DEFECT'S CLASS, AND POINT AT THE ARTIFACT THAT HOLDS IT.
    # unresolved_citations already computes WHICH kind of failure each one is; this
    # used to flatten all of them under one "your citations do not resolve" banner
    # with the TEST path leading every line. Measured 2026-09-19 (Maya 🌻): of six
    # offenders, five were not test-side fixable at all — the citation was right and
    # the row's io/phase2 note simply did not name the method. An author sent to edit
    # the test finds nothing wrong with it, and then discounts the next red too.
    # A failure message that names the wrong artifact is a wrong MECHANISM, not a
    # wrong number: a wrong number gets re-derived, a wrong mechanism sends someone
    # into innocent code.
    assert not offenders, report_by_class( offenders )


# The checker must be able to say no. These feed it citations built to fail
# against the REAL files at HEAD, one per reason and one per file type.

# The REPORTER must be able to tell the two classes apart, and must send the reader
# to the artifact that actually holds each defect. Maya 🌻 found this code unguarded
# on 2026-09-19: it lived inside an assertion message, which only renders on failure,
# so the suite was green whether the routing was right or wrong.

CITE_OFFENDER = ( "src/tests/e2e_ui/test_a.py", "A-2 #9", "notifications.js:5-6",
                  "names no legacy method on its line" )
NOTE_OFFENDER = ( "src/tests/e2e_ui/test_b.py", "A-2 #10", "notifications.js:100-200",
                  f"loadJobHistory {NOTE_REASON}" )


def test_the_report_sends_a_citation_defect_to_the_test():
    report = report_by_class( [ CITE_OFFENDER ] )

    assert "CITATION defect" in report
    assert "FIX THE TEST'S HEADER" in report
    assert CITE_OFFENDER[ 0 ] in report
    assert "NOTE defect" not in report, "a citation defect must not be reported as a note defect"


def test_the_report_sends_a_note_defect_to_the_note_and_not_the_test():
    report = report_by_class( [ NOTE_OFFENDER ] )

    assert "NOTE defect" in report
    assert "DO NOT EDIT THE TEST" in report
    assert PHASE2_DIR_REL in report, "a note defect must name the directory that holds the note"
    assert "loadJobHistory" in report, "it must name the method the note is missing"
    assert "CITATION defect" not in report, "a note defect must not be reported as a citation defect"


def test_the_report_separates_the_two_classes_and_drops_neither():
    report = report_by_class( [ CITE_OFFENDER, NOTE_OFFENDER ] )

    assert "1 CITATION defect(s)" in report, "the counts must stay separable"
    assert "1 NOTE defect(s)" in report
    # Every offender appears, so a mixed batch cannot silently lose one class.
    assert CITE_OFFENDER[ 0 ] in report and NOTE_OFFENDER[ 0 ] in report


def test_the_report_omits_a_class_that_has_no_offenders():
    # The control for the two tests above: they would also pass if the reporter
    # always emitted both headings. It does not.
    assert "NOTE defect" not in report_by_class( [ CITE_OFFENDER ] )
    assert "CITATION defect" not in report_by_class( [ NOTE_OFFENDER ] )


def test_an_out_of_range_js_citation_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    header = f"// `onTTSPlaybackComplete` (notifications.js:{end}-{end + 5})"
    problems = unresolved_citations( header, legacy_bodies, legacy_spans, [] )
    assert [ reason.split( " (" )[ 0 ] for _, reason in problems ] == [ "not inside the method it names" ]


def test_an_out_of_range_html_citation_is_red( legacy_bodies, legacy_spans ):
    ( open_line, close_line ), = legacy_spans[ "tts-pause-btn" ]
    header = f"// `#tts-pause-btn` (notifications.html:{open_line}-{close_line + 1})"
    problems = unresolved_citations( header, legacy_bodies, legacy_spans, [] )
    assert [ reason.split( " (" )[ 0 ] for _, reason in problems ] == [ "not inside the element id it names" ]


def test_a_citation_past_the_end_of_the_file_is_red( legacy_bodies, legacy_spans ):
    header = "// `onTTSPlaybackComplete` (notifications.js:999999-1000001)"
    assert unresolved_citations( header, legacy_bodies, legacy_spans, [] ), "a line past EOF resolved"


def test_a_citation_that_names_nothing_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    problems = unresolved_citations(
        f"// the playback-complete path (notifications.js:{start}-{end})\n"
        "// the header of the queue (notifications.html:434)",
        legacy_bodies, legacy_spans, [] )
    assert [ reason for _, reason in problems ] == [
        "names no legacy method on its line", "names no legacy element id on its line" ]


def test_a_backwards_range_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    header = f"// `onTTSPlaybackComplete` (notifications.js:{end}-{start})"
    assert [ r for _, r in unresolved_citations( header, legacy_bodies, legacy_spans, [] ) ] == [ "range runs backwards" ]


def test_a_name_missing_from_the_rows_note_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    header = f"// `onTTSPlaybackComplete` (notifications.js:{start}-{end})"
    assert not unresolved_citations( header, legacy_bodies, legacy_spans, [ "names onTTSPlaybackComplete" ] )
    assert [ r for _, r in unresolved_citations( header, legacy_bodies, legacy_spans, [ "names nothing useful" ] ) ] == [
        "onTTSPlaybackComplete is not named in the row's note" ]


def test_the_manifest_row_notes_are_found( manifest_text, project_root ):
    """A-2 #2d names two notes, A-0 names none, and a key the manifest lacks names none."""
    note_dir = project_root / PHASE2_DIR_REL
    assert len( row_notes( manifest_text, "A-2 #2d", note_dir ) ) == 2
    assert row_notes( manifest_text, "A-0", note_dir ) == []
    assert row_notes( manifest_text, "Z-9", note_dir ) == []
