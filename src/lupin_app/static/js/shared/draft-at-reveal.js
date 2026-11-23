/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.

// The answer a card's controls hold at the moment the forecast fold opens: the rules both clients share.
//
// The seen route stores it as prediction_log.draft_at_reveal, so the server can tell an answer given
// unaided from one switched after the forecast was shown. The shape is the one exposure.py documents:
// { value: <the string the submit button would send with the controls as they stand> }.
//
// Each client reads its own controls, because the markup differs, and hands what it read to buildDraft.
// This file holds what must not differ: the empty rules, the wire text and the size limit.
// The notifications page reads the published window.LUPIN_DRAFT_AT_REVEAL; the multiplexer imports the module.

/** The server's limit on a draft, counted in characters of its JSON text. */
export const DRAFT_MAX_CHARS = 4096;

/**
 * Count a draft the way the route does: as Python's json.dumps writes it.
 *
 * json.dumps puts a space after the colon. It writes every character outside space to tilde as a six-character escape.
 * So a character beyond Basic Latin counts six, and an emoji, which is two UTF-16 units, counts twelve.
 *
 * Requires:
 *   - draft is { value: string }
 *
 * Ensures:
 *   - returns the length json.dumps gives the same draft on the server
 *
 * @param {import("./draft-at-reveal.js").DraftAtReveal} draft
 * @returns {number}
 */
export function routeLength( draft ) {
  const text = JSON.stringify( draft );
  let length = text.length + 1;
  for ( let i = 0; i < text.length; i++ ) {
    if ( text.charCodeAt( i ) > 0x7e ) length += 5;
  }
  return length;
}

/**
 * Say what a card's answer would be if submitted now, from what the client read.
 *
 * Requires:
 *   - responseType is the card's response type
 *   - parts.text is the open-ended box's text, as typed
 *   - parts.batch is [ [ header, text ] ] for each batch field, as typed
 *   - parts.saved holds the multiple-choice answers saved so far, { header: pick or [picks] }
 *   - parts.shown is { header, value } for the question on screen, or a falsy value when nothing is chosen
 *
 * Ensures:
 *   - a yes/no card, or any other type, returns null, because choosing is submitting
 *   - an open-ended card returns its trimmed text, or null when the box is empty
 *   - a batch card returns its non-empty trimmed fields, and a multiple-choice card the saved answers plus the question on screen,
 *     as the JSON text of { answers: { header: pick or [picks] } }, or null when no answer is held
 *   - returns null when the draft would be over DRAFT_MAX_CHARS as the route counts it (routeLength)
 *   - never returns an empty value
 *
 * @param {string | undefined} responseType
 * @param {import("./draft-at-reveal.js").DraftParts} parts
 * @returns {import("./draft-at-reveal.js").DraftAtReveal | null}
 */
export function buildDraft( responseType, parts ) {
  let wire = null;
  if ( responseType === "open_ended" ) {
    const text = parts.text.trim();
    wire = text === "" ? null : text;
  } else if ( responseType === "open_ended_batch" ) {
    /** @type {Record<string, string>} */
    const answers = {};
    for ( const [ header, raw ] of parts.batch ) {
      const text = raw.trim();
      if ( text !== "" ) answers[ header ] = text;
    }
    wire = Object.keys( answers ).length === 0 ? null : JSON.stringify( { answers } );
  } else if ( responseType === "multiple_choice" ) {
    const answers = { ...parts.saved };
    if ( parts.shown ) answers[ parts.shown.header ] = parts.shown.value;
    wire = Object.keys( answers ).length === 0 ? null : JSON.stringify( { answers } );
  }
  if ( wire === null ) return null;
  const draft = { value: wire };
  return routeLength( draft ) > DRAFT_MAX_CHARS ? null : draft;
}

/**
 * Puts the surface on a window object as `LUPIN_DRAFT_AT_REVEAL`.
 *
 * @param {any} win
 */
export function publishOnWindow( win ) {
  win.LUPIN_DRAFT_AT_REVEAL = { DRAFT_MAX_CHARS, routeLength, buildDraft };
}

// The classic-script bridge: notifications.js reads the global when it is called.
// The declaration is in window-globals.d.ts.
/* c8 ignore next */ // tsx adds an empty never-run range at the file tail; the publish line itself is run and asserted.
publishOnWindow( globalThis );
