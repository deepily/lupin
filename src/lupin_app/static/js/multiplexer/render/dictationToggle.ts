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
import { setValueFocusCaret } from "./dom";

/** The slice of the recording manager a dictation mic drives. */
export interface DictationRecorderLike {
  startRecording( opts: RecordingManagerStartOptions ): Promise<void>;
  stopRecording( contextId: string ): Promise<void>;
  getActiveContextId(): string | null;
}

/** The text and selection an input held when a recording began. */
export interface DictationStash {
  text     : string;
  selStart : number | null;
  selEnd   : number | null;
}

/** What starting one dictation needs, and the ways the mics differ. */
export interface DictationStartOptions {
  /** Only the start call is used, so a recorder without an active-context read will do. */
  recorder     : Pick<DictationRecorderLike, "startRecording">;
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
  /**
   * True: splice at the live caret, then fire an `input` event.
   *
   * Absent: splice at the caret held when recording began.
   */
  liveCaret   ?: boolean;
  /** True: the words arrive through setValueFocusCaret, so the input takes focus. */
  focusAfterInsert ?: boolean;
  /** Called once with the stash, before the recorder starts. */
  onStart     ?: ( stash: DictationStash ) => void;
  /**
   * Gives the text the words are spliced into when they arrive.
   *
   * Absent: the stash taken at the start. Given: its answer, so a card that resets its own record mid-recording keeps that reset.
   */
  currentStash ?: () => DictationStash;
  /** Called after the words are in the input, with the new value and caret (null: none). */
  afterInsert ?: ( spliced: { value: string; caret: number | null } ) => void;
  /** Called after the button is reset, when the recorder reports an error. */
  onError     ?: ( err: { type: string; message: string; originalError: unknown } ) => void;
  /** Called after the button is reset on a cancel, with the stash taken at the start. */
  onCancel    ?: ( stash: DictationStash ) => void;
}

/** What one mic click needs, and the ways the mics differ. */
export interface DictationToggleOptions extends Omit<DictationStartOptions, "recorder"> {
  recorder     : DictationRecorderLike;
  /** True: a click while another context records stops that one and starts nothing. */
  stopOther   ?: boolean;
}

/**
 * Start one dictation: stash the input, show recording, splice the transcription in.
 *
 * The part of a mic click every dictation mic shares. A mic that keeps its own record of whether it is recording
 * calls this directly, and `toggleDictation` calls it after its stop and guard checks.
 *
 * Requires:
 *   - `recorder` has startRecording, or is a test double of it
 *
 * Ensures:
 *   - the stash is the input's text and selection now, and onStart sees it before the recorder starts
 *   - the button shows `recording` until the recorder reports a transcription, an error or a cancel
 *   - a transcription is spliced into the stash's text, or the stash currentStash names, and every outcome returns the button to idle
 *   - afterInsert, onError and onCancel run after the button is reset
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function startDictation( o: DictationStartOptions ): void {
  const { recorder, contextId, button, input, processing } = o;
  const stash  = { text: input.value, selStart: input.selectionStart, selEnd: input.selectionEnd };
  const settle = (): void => {
    processing?.delete( contextId );
    button.classList.remove( "recording", "processing" );
  };
  o.onStart?.( stash );
  button.classList.add( "recording" );
  void recorder.startRecording( {
    contextId,
    authToken  : o.authToken(),
    onComplete : ( transcription ) => {
      settle();
      const base    = o.currentStash === undefined ? stash : o.currentStash();
      const spliced = o.liveCaret === true
        ? insertTranscriptionText( input.value, input.selectionStart, input.selectionEnd, transcription ?? "" )
        : insertTranscriptionText( base.text, base.selStart, base.selEnd, transcription ?? "" );
      if ( o.focusAfterInsert === true ) setValueFocusCaret( input, spliced.value, spliced.caret );
      else {
        input.value = spliced.value;
        if ( spliced.caret !== null ) input.setSelectionRange( spliced.caret, spliced.caret );
      }
      if ( o.liveCaret === true ) input.dispatchEvent( new Event( "input", { bubbles: true } ) );
      o.afterInsert?.( spliced );
    },
    onError    : ( err ) => {
      settle();
      o.onError?.( err );
    },
    onCancel   : () => {
      settle();
      o.onCancel?.( stash );
    },
  } );
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
  const { recorder, contextId, button, processing } = o;
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
  startDictation( o );
}
