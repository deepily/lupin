// Row schema — rowSchema unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// THE DEFECT CLASS THIS PINS: a hard-coded colspan. The JS card's own
// docstring records that these were once literals — 12, 12, 11, 5, 5, 5, 5
// across seven sites — and that "a stale colspan does not look broken: the
// table still renders perfectly while the controls row and the error stripe
// quietly stop spanning it." So the assertions below deliberately DERIVE the
// expected width from the schema rather than writing 6, except in one place
// where a literal is the whole point (see the note there).

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ROW_SCHEMA,
  ROW_FIELD_LABELS,
  rowWidth,
  rowFieldLabel,
  disclosedFields,
} from "../../../lupin_app/static/js/multiplexer/render/rowSchema";

// ---------------------------------------------------------------- the split

test( "line1 is the VISIBLE five, in the JS card's order", () => {
  // Order is observable — it is the column order the operator reads.
  assert.deepEqual( [ ...ROW_SCHEMA.line1 ],
    [ "id", "title", "class", "status", "priority" ] );
} );

test( "line2 and line3 are the DISCLOSED fields, in the JS card's order", () => {
  assert.deepEqual( [ ...ROW_SCHEMA.line2 ],
    [ "blocked", "chase", "accountable", "filer", "project" ] );
  assert.deepEqual( [ ...ROW_SCHEMA.line3 ], [ "detail", "actions" ] );
} );

test( "PRIORITY is visible and FILER is disclosed — not the other way round", () => {
  // Both were wrong in the pre-disclosure TS row: priority was absent from the
  // visible line and filer was absent from the client entirely. Rick asked for
  // the filer column by voice on 2026-09-02.
  assert.ok(  ROW_SCHEMA.line1.includes( "priority" ) );
  assert.ok(  ROW_SCHEMA.line2.includes( "filer" ) );
  assert.ok( !ROW_SCHEMA.line1.includes( "filer" ) );
} );

test( "the three lines are DISJOINT — no field is both visible and disclosed", () => {
  const all = [ ...ROW_SCHEMA.line1, ...ROW_SCHEMA.line2, ...ROW_SCHEMA.line3 ];
  assert.equal( new Set( all ).size, all.length );
} );

// ---------------------------------------------------------------- width

test( "rowWidth is the visible fields PLUS the disclosure cell", () => {
  // Derived, not written: if line1 grows, this assertion follows it.
  assert.equal( rowWidth(), ROW_SCHEMA.line1.length + 1 );
} );

test( "rowWidth is 6 today — the one deliberate literal in this file", () => {
  // A purely derived assertion cannot catch the schema itself being edited by
  // accident: change line1 and every derived check moves with it, silently.
  // This literal is the anchor that makes such a change VISIBLE. If you meant
  // to change the schema, change this number in the same commit.
  assert.equal( rowWidth(), 6 );
} );

// ---------------------------------------------------------------- labels

test( "every field in every line has a label", () => {
  const all = [ ...ROW_SCHEMA.line1, ...ROW_SCHEMA.line2, ...ROW_SCHEMA.line3 ];
  // Positive control: a corpus that silently emptied would pass the loop.
  assert.equal( all.length, 12 );
  for ( const f of all ) {
    assert.equal( typeof ROW_FIELD_LABELS[ f ], "string", `no label for ${ f }` );
    assert.ok( ROW_FIELD_LABELS[ f ].length > 0, `empty label for ${ f }` );
  }
} );

test( "labels match the JS card verbatim where they differ from the field name", () => {
  // These five are the ones a paraphrase would get wrong.
  assert.equal( rowFieldLabel( "blocked" ),     "Blocked by" );
  assert.equal( rowFieldLabel( "chase" ),       "Next chase" );
  assert.equal( rowFieldLabel( "filer" ),       "Filed by" );
  assert.equal( rowFieldLabel( "accountable" ), "Accountable" );
  assert.equal( rowFieldLabel( "id" ),          "ID" );
} );

test( "an UNKNOWN field degrades to its own name, never undefined", () => {
  // A missing label must not print "undefined" into a header cell.
  assert.equal( rowFieldLabel( "not_a_field" ), "not_a_field" );
} );

// ---------------------------------------------------------------- disclosed

test( "disclosedFields returns line2 then line3 as TWO separate lines", () => {
  const lines = disclosedFields();
  assert.equal( lines.length, 2 );
  assert.deepEqual( [ ...lines[ 0 ] ], [ ...ROW_SCHEMA.line2 ] );
  assert.deepEqual( [ ...lines[ 1 ] ], [ ...ROW_SCHEMA.line3 ] );
} );

test( "disclosedFields contains NO visible field", () => {
  const disclosed = disclosedFields().flat();
  for ( const f of ROW_SCHEMA.line1 ) {
    assert.ok( !disclosed.includes( f ), `${ f } is visible and must not be disclosed` );
  }
} );
