/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
//
// The click logic every dictation mic shares (row 9cc37a94 item 32).
// Finding d-06e7e21372.
//
// Three handlers held the same toggle: createActionRequiredMic (actionRequiredMic.ts),
// makeNewTicketDictationHook (newTicketCard.ts) and TaskRowController.handleReasonMicClick.
// They differ in four small ways, and those four are the options below.

import type { RecordingManagerStartOptions } from "../audio/recordingManager";
import { insertTranscriptionText } from "./insertTranscriptionText";

/** The slice of the recording manager a dictation mic drives. */
export interface DictationRecorderLike {
  startRecording( opts: RecordingManagerStartOptions ): Promise<void>;
  stopRecording( contextId: string ): Promise<void>;
  getActiveContextId(): string | null;
}

/** What one mic click needs, and the four ways the three mics differ. */
export interface DictationToggleOptions {
  recorder     : DictationRecorderLike;
  /** Reads the auth token for the upload, called only when a recording starts. */
  authToken    : () => string | null;
  contextId    : string;
  button       : HTMLButtonElement;
  input        : HTMLInputElement | HTMLTextAreaElement;
  /**
   * Contexts waiting for a transcription.
   *
   * Given: the guard lives here. Absent: the button's `processing` class is the guard.
   */
  processing  ?: Set<string>;
  /** True: a click while another context records stops that one and starts nothing. */
  stopOther   ?: boolean;
  /**
   * True: splice at the live caret, then fire an `input` event.
   *
   * Absent: splice at the caret held when recording began.
   */
  liveCaret   ?: boolean;
  /** Called after the button is reset, when the recorder reports an error. */
  onError     ?: ( err: { type: string; message: string; originalError: unknown } ) => void;
}

/**
 * Start, stop or ignore a dictation, for one mic click.
 *
 * Requires:
 *   - `recorder` is the recording manager, or a test double of its three methods
 *
 * Ensures:
 *   - a click while this mic is processing does nothing
 *   - a click while this context records stops it and marks the button `processing`
 *   - with `stopOther`, a click while another context records stops that one and starts nothing
 *   - otherwise recording starts and the button shows `recording`
 *   - a transcription is spliced into the input, and every outcome returns the button to idle
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function toggleDictation( o: DictationToggleOptions ): void {
  const { recorder, contextId, button, input, processing } = o;
  if ( processing === undefined ? button.classList.contains( "processing" ) : processing.has( contextId ) ) return;

  const active = recorder.getActiveContextId();
  if ( active === contextId ) {
    processing?.add( contextId );
    button.classList.remove( "recording" );
    button.classList.add( "processing" );
    void recorder.stopRecording( contextId );
    return;
  }
  // Another mic's recording is stopped, not cancelled: starting here would make the recorder
  // cancel it (single-active) and throw its dictation away (row 2ebf322f review finding 2).
  if ( o.stopOther === true && active !== null ) {
    void recorder.stopRecording( active );
    return;
  }

  const stash  = { text: input.value, selStart: input.selectionStart, selEnd: input.selectionEnd };
  const settle = (): void => {
    processing?.delete( contextId );
    button.classList.remove( "recording", "processing" );
  };
  button.classList.add( "recording" );
  void recorder.startRecording( {
    contextId,
    authToken  : o.authToken(),
    onComplete : ( transcription ) => {
      settle();
      const spliced = o.liveCaret === true
        ? insertTranscriptionText( input.value, input.selectionStart, input.selectionEnd, transcription )
        : insertTranscriptionText( stash.text, stash.selStart, stash.selEnd, transcription );
      input.value = spliced.value;
      if ( spliced.caret !== null ) input.setSelectionRange( spliced.caret, spliced.caret );
      if ( o.liveCaret === true ) input.dispatchEvent( new Event( "input", { bubbles: true } ) );
    },
    onError    : ( err ) => {
      settle();
      o.onError?.( err );
    },
    onCancel   : settle,
  } );
}
