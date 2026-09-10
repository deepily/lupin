/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer — the TTS preview limiter (P0, Rick's broadcast a090b845, 2026-09-10).
//
// WHAT BROKE: Rick has the TTS slider at 0% on the legacy page and the multiplexer
// spoke 100% of every notification. The multiplexer HAD a slider
// (TtsPreviewSliderRenderer) that persisted the fraction, but nothing on the speech
// path read it — wireTtsIntent enqueued `ttsText` whole. It went unnoticed until
// 7221b484 made the tab receive notifications at all (before that, a shared WebSocket
// session id left it deaf, so it spoke nothing).
//
// A straight port of legacy notifications.js `_computeTTSPreview` and
// `_truncateAtBoundary` (src/rnd/v0.1.7/2026.05.22-tts-limiter-boundary-scan.md):
//   - fraction === 0                          → "skip": nothing is spoken
//   - disabled, fraction >= 1, or shorter
//     than minChars                           → "full": the whole text
//   - otherwise                               → "preview": cut forward from the
//                                               fraction mark at the next boundary;
//                                               "full" if that reaches the end
// Pure: no DOM, no storage, no bus.

export type TtsPreviewStage = "full" | "preview" | "skip";

export interface TtsPreviewSettings {
  fraction : number;    // slider fraction in [0, 1]
  enabled  : boolean;   // INI `tts preview enabled` (legacy: false until config loads)
  minChars : number;    // INI `tts preview min chars` (legacy default 100)
}

export interface TtsPreview {
  stage : TtsPreviewStage;
  text  : string;       // what to speak; "" for "skip"
}

// Abbreviations whose periods must not count as boundaries. Masking is
// length-preserving, so every character index stays valid. Legacy list, verbatim.
const ABBREVIATIONS: ReadonlyArray<string> = [
  "Mr.", "Mrs.", "Ms.", "Mx.", "Dr.", "Prof.", "Sr.", "Jr.", "Rev.",
  "St.", "Mt.", "Ft.", "Ave.", "Blvd.", "Rd.",
  "vs.", "e.g.", "i.e.", "etc.", "viz.", "cf.", "No.",
  "a.m.", "p.m.", "A.M.", "P.M.",
];
const ABBR_MASK          = "";         // SOH — never appears in real TTS text
const SENTENCE_TERMINALS = ".!?;";
const DASHES             = "—–";   // em-dash, en-dash (NOT hyphen-minus)

/**
 * Truncate `text` to roughly `fraction` of its length, extending forward to the next
 * natural boundary.
 *
 * Requires:
 *   - fraction is a number; values >= 1 return the whole text
 *
 * Ensures:
 *   - "" for empty text; the trimmed text when fraction >= 1
 *   - otherwise scans forward from ceil( length × fraction ) for the first newline,
 *     em/en-dash, or `.!?;` followed by whitespace or end of text, and cuts inclusive
 *   - with no boundary, cuts at the next space (never silently expands to 100%)
 *   - abbreviation periods (Mr., e.g., a.m.) are never boundaries
 */
export function truncateAtBoundary( text: string, fraction: number ): string {
  if ( !text ) return "";
  if ( fraction >= 1 ) return text.trim();

  let masked = text;
  for ( const abbr of ABBREVIATIONS ) {
    masked = masked.split( abbr ).join( abbr.replace( /\./g, ABBR_MASK ) );
  }

  const targetPos = Math.ceil( masked.length * fraction );

  let cut = -1;
  for ( let i = targetPos; i < masked.length; i++ ) {
    const ch   = masked[ i ] as string;
    const next = masked[ i + 1 ];   // undefined at end of text
    if ( ch === "\n" || DASHES.includes( ch ) ) {
      cut = i;
      break;
    }
    if ( SENTENCE_TERMINALS.includes( ch ) && ( next === undefined || /\s/.test( next ) ) ) {
      cut = i;
      break;
    }
  }

  let slice: string;
  if ( cut !== -1 ) {
    slice = masked.slice( 0, cut + 1 );
  } else {
    const ws = masked.indexOf( " ", targetPos );
    slice = ws === -1 ? masked : masked.slice( 0, ws );
  }

  return slice.split( ABBR_MASK ).join( "." ).trim();
}

/**
 * Decide what, if anything, to speak for one notification.
 *
 * Requires:
 *   - settings.fraction is in [0, 1]
 *
 * Ensures:
 *   - { stage: "skip", text: "" } when the slider is at 0 — checked FIRST, so it holds
 *     even while the feature flag is still loading (legacy order)
 *   - { stage: "full", text } when disabled, at 100%, shorter than minChars, or when
 *     the boundary cut reaches the end of the text
 *   - { stage: "preview", text: <cut> } otherwise
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as wireTtsIntent.ts).
export function computeTtsPreview( text: string, settings: TtsPreviewSettings ): TtsPreview {
  if ( settings.fraction === 0 ) return { stage: "skip", text: "" };

  if ( !settings.enabled || settings.fraction >= 1 || text.length < settings.minChars ) {
    return { stage: "full", text };
  }

  const preview = truncateAtBoundary( text, settings.fraction );
  if ( preview.length >= text.trim().length ) return { stage: "full", text };

  return { stage: "preview", text: preview };
}
