/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP13 — TtsPreviewSliderRenderer (F6).
//
// Owns the TTS preview-fraction slider control. Ports legacy
// notifications.js:1613-1640 + the config-seed layering at :804-811.
//
// Fraction-resolution layering (parity with legacy):
//   1. INI default seed — `tts_preview_fraction` from /api/multiplexer/config,
//      passed in as `iniDefaultFraction` (boot fetches it; the renderer never
//      fetches — keeps it pure + testable).
//   2. User runtime override — persisted via StorageService under
//      `tts_preview_fraction` (schema 1). A valid stored override WINS over the
//      INI default (legacy localStorage-layered-on-INI semantics).
//
// Lifecycle (mirrors TtsChromeRenderer F-26 contract):
//   - mount(root) renders the control seeded to the resolved fraction; throws
//     on a second mount without an intervening unmount().
//   - unmount() removes the DOM + drops the label ref. Idempotent.
//
// The slider does NOT itself truncate TTS text — it persists the runtime
// fraction + fires `onChange(fraction)` so the boot consumer (last thin wiring
// step) routes it to whatever reads the preview fraction. Scope parity with the
// legacy control, which likewise only owns `this.ttsPreviewFraction`.

import type { StorageService } from "../shared/StorageService";
import { renderTtsPreviewSlider } from "./templates/ttsPreviewSlider";

// StorageService key + schema for the persisted runtime override. The legacy
// key was `notifications_tts_preview_fraction_runtime` (raw float string); the
// multiplexer uses the StorageService envelope under this prefixed key.
export const TTS_FRACTION_STORAGE_KEY    = "tts_preview_fraction";
export const TTS_FRACTION_STORAGE_SCHEMA = 1;

// Conservative fallback when neither a valid stored override nor a valid INI
// default is available — matches legacy `this.ttsPreviewFraction = 0.25`.
export const DEFAULT_TTS_FRACTION = 0.25;

interface StoredFraction {
  fraction : number;
}

/**
 * Return `f` when it is a finite fraction in [0, 1]; otherwise `null`.
 *
 * Requires: nothing (accepts arbitrary input for defensive validation).
 * Ensures: returns the input unchanged iff it is a finite number in [0, 1].
 */
export function clampFraction( f: unknown ): number | null {
  if ( typeof f !== "number" ) return null;
  if ( !Number.isFinite( f ) ) return null;
  if ( f < 0 || f > 1 ) return null;
  return f;
}

/**
 * Resolve the initial fraction from a stored override layered on the INI default.
 *
 * Requires: nothing.
 * Ensures:
 *   - a valid stored override wins;
 *   - else a valid INI default is used;
 *   - else DEFAULT_TTS_FRACTION.
 */
export function resolveInitialFraction(
  storedOverride   : unknown,
  iniDefaultFraction : unknown,
): number {
  const stored = clampFraction( storedOverride );
  if ( stored !== null ) return stored;
  const ini = clampFraction( iniDefaultFraction );
  if ( ini !== null ) return ini;
  return DEFAULT_TTS_FRACTION;
}

export interface TtsPreviewSliderRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Detach: remove DOM + drop refs. Idempotent. */
  unmount(): void;
  /** Current runtime fraction in [0, 1]. */
  getFraction(): number;
  /**
   * Apply the server INI default (from the non-blocking /api/multiplexer/config
   * fetch, which resolves AFTER mount). No-op when the user already has a stored
   * override or has moved the slider this session, or when `fraction` is
   * out-of-range. Updates the live slider + label when mounted.
   */
  seedIniDefault( fraction: number ): void;
}

export interface TtsPreviewSliderRendererOptions {
  storage            : StorageService;
  /** INI default fraction from /api/multiplexer/config (boot-supplied). */
  iniDefaultFraction : number;
  /** Optional consumer notified on every user change (boot wiring). */
  onChange?          : ( fraction: number ) => void;
}

class TtsPreviewSliderRendererImpl implements TtsPreviewSliderRenderer {
  private readonly storage  : StorageService;
  private readonly onChange : ( ( fraction: number ) => void ) | null;

  private fraction : number;
  private root     : HTMLElement | null = null;
  private label    : HTMLElement | null = null;
  private input    : HTMLInputElement | null = null;
  private mounted  = false;
  // True once a valid stored override exists OR the user moves the slider this
  // session — a late INI-default seed must NOT clobber the user's choice.
  private userOverride : boolean;

  constructor( opts: TtsPreviewSliderRendererOptions ) {
    this.storage  = opts.storage;
    this.onChange = opts.onChange ?? null;

    const stored = this.storage.getJSON<StoredFraction>(
      TTS_FRACTION_STORAGE_KEY,
      TTS_FRACTION_STORAGE_SCHEMA,
    );
    const storedFraction = stored === null ? null : clampFraction( stored.fraction );
    this.userOverride = storedFraction !== null;
    this.fraction = resolveInitialFraction( storedFraction, opts.iniDefaultFraction );
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "TtsPreviewSliderRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    const control = renderTtsPreviewSlider(
      { percent: this.fraction * 100 },
      { onInput: ( pct ): void => this.onSliderInput( pct ) },
    );
    this.label = control.querySelector<HTMLElement>( ".tts-preview-slider-value" );
    this.input = control.querySelector<HTMLInputElement>( ".tts-preview-slider-input" );
    root.replaceChildren( control );
  }

  unmount(): void {
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.label = null;
    this.input = null;
    this.mounted = false;
  }

  getFraction(): number {
    return this.fraction;
  }

  seedIniDefault( fraction: number ): void {
    if ( this.userOverride ) return;           // user choice wins over a late INI seed
    const f = clampFraction( fraction );
    if ( f === null ) return;
    this.fraction = f;
    const pct = f * 100;
    if ( this.input !== null ) this.input.value = String( pct );
    if ( this.label !== null ) this.label.textContent = `${pct}%`;
  }

  // -------------------------------------------------------------------------
  // Input handler
  // -------------------------------------------------------------------------

  private onSliderInput( pct: number ): void {
    const fraction = clampFraction( pct / 100 );
    /* c8 ignore next */ // defensive: the range input only emits snapped step values in [0,100], so pct/100 is always a valid fraction; the null guard isolates a hypothetically-tampered DOM value.
    if ( fraction === null ) return;

    this.fraction = fraction;
    this.userOverride = true;   // a session move also wins over a late INI seed
    if ( this.label !== null ) {
      this.label.textContent = `${pct}%`;
    }
    this.storage.setJSON<StoredFraction>(
      TTS_FRACTION_STORAGE_KEY,
      { fraction },
      TTS_FRACTION_STORAGE_SCHEMA,
    );
    if ( this.onChange !== null ) this.onChange( fraction );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTtsPreviewSliderRenderer(
  opts: TtsPreviewSliderRendererOptions,
): TtsPreviewSliderRenderer {
  return new TtsPreviewSliderRendererImpl( opts );
}
