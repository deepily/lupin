"""
Legacy notifications.js must not console.log a whole DOM element or a tagged debug dump
(row f63cef62).

MEASURED 2026-09-23 (Chloe, row edd3483d): the open-ended response path logged
`console.log( '[DEBUG] Input element found:', input )`, and the TypeScript tier's log
carried a 5,334-line dump of that one HTMLInputElement — memory and log size for a line no
user needs. The three `[DEBUG]` lines beside it dumped the whole notification object.

The predicate is "no console.log call hands a DOM-element variable, or carries a [DEBUG]
tag, in this file" — not "these six lines are gone". A guard for the six lines would let the
next debug dump in.
"""
import re
from pathlib import Path

from cosa.utils import util as cu

JS = Path( cu.get_project_root() ) / "src" / "lupin_app" / "static" / "js" / "notifications.js"

DEBUG_TAG   = re.compile( r"console\.log\(\s*['\"`]\[DEBUG\]" )
# A string label followed by a bare DOM-ish identifier: console.log( 'x:', input )
DOM_ARG     = re.compile( r"console\.log\(\s*(['\"`])[^'\"`]*\1\s*,\s*(input|card|el|element|button|container|target)\s*[,)]" )


def _offenders( text ):
    return [ ( n, line.strip() ) for n, line in enumerate( text.splitlines(), 1 )
             if DEBUG_TAG.search( line ) or DOM_ARG.search( line ) ]


def test_the_file_was_found_and_is_the_big_legacy_one():
    assert JS.is_file(), JS
    assert len( JS.read_text().splitlines() ) > 20000


def test_notifications_js_logs_no_dom_element_and_no_tagged_debug_dump():
    assert _offenders( JS.read_text() ) == []


def test_the_detector_catches_the_original_defect_and_ignores_a_scalar_log():
    """Positive control: the lines that were removed are flagged; a log of a string is not."""
    assert _offenders( "console.log( '[DEBUG] Input element found:', input );" )
    assert _offenders( "console.log( 'row:', card );" )
    assert _offenders( "console.log( '[DEBUG] response_default type:', typeof x );" )
    assert _offenders( "console.log( 'id:', input.id );" ) == []
    assert _offenders( "console.log( `[COMMONS-ACTIVITY] load start, window=${w}` );" ) == []
