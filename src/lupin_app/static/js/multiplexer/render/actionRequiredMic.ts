/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity A-2 #2j / #2k / #2l — the 🎤 on an Action Required card.
//
// Legacy drives every card mic through recordingManager.startRecording(contextId, button, input)
// (notifications.js:3752+): a click starts recording (`.recording`), a second click on the same
// context stops it (`.processing` while the audio is transcribed), and the transcription is
// inserted at the caret (_insertTranscriptionText, :3653-3675) followed by an `input` event so
// the field's own validation runs (:3843-3844). An error or a cancel resets the button
// (_resetButton). A click while ANY other context records stops that one and starts nothing
// (legacy `if ( isRecording() ) stopRecording()`, :26028 / :26052 / :13354). The contexts are legacy's: `yn-comment-<id>` (yes_no comment),
// `response-input-<id>` (open_ended), `mc-<id>` (multiple_choice "Other", :26057).
//
// The template renders the button and hands (contextId, button, input) to this handler, so it
// stays free of the recorder; the renderer builds the handler with the recorder it was given.

import type { RecordingManagerStartOptions } from "../audio/recordingManager";
import { insertTranscriptionText } from "./insertTranscriptionText";

/** The slice of `recordingManager` a card mic drives. */
export interface ActionRequiredRecorderLike {
  startRecording( opts: RecordingManagerStartOptions ): Promise<void>;
  stopRecording( contextId: string ): Promise<void>;
  getActiveContextId(): string | null;
}

/** What a card mic click calls: the context, the button, and the field the words go into. */
export type ActionRequiredMicHandler = ( contextId: string, button: HTMLButtonElement, input: HTMLInputElement ) => void;

/**
 * Build the handler a card's 🎤 calls.
 *
 * Requires:
 *   - recorder is the recording manager (or a test double of its three methods)
 *
 * Ensures:
 *   - a click while this context records stops it, and the button shows `.processing`
 *   - a click while the button is `.processing` does nothing
 *   - a click while another context records stops that context and starts nothing
 *   - otherwise it starts recording for this context, the button shows `.recording`, and:
 *       · on a transcription the text goes in at the caret (appended when the field has none),
 *         the caret lands after it, and an `input` event fires so validation runs
 *       · on a transcription, an error or a cancel the button returns to idle
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as wireTtsIntent.ts).
export function createActionRequiredMic(
  recorder     : ActionRequiredRecorderLike,
  getAuthToken : () => string | null,
): ActionRequiredMicHandler {
  return ( contextId, button, input ) => {
    if ( button.classList.contains( "processing" ) ) return;
    const active = recorder.getActiveContextId();
    if ( active === contextId ) {
      button.classList.remove( "recording" );
      button.classList.add( "processing" );
      void recorder.stopRecording( contextId );
      return;
    }
    // Legacy `if ( isRecording() ) stopRecording()`: another mic's recording is stopped — it
    // uploads into its own field — and nothing starts. Starting here would make the recorder
    // CANCEL it (single-active), throwing that dictation away (row 2ebf322f review finding 2).
    if ( active !== null ) {
      void recorder.stopRecording( active );
      return;
    }
    const reset = (): void => { button.classList.remove( "recording", "processing" ); };
    button.classList.add( "recording" );
    void recorder.startRecording( {
      contextId,
      authToken  : getAuthToken(),
      onComplete : ( transcription ) => {
        reset();
        const spliced = insertTranscriptionText( input.value, input.selectionStart, input.selectionEnd, transcription );
        input.value = spliced.value;
        if ( spliced.caret !== null ) input.setSelectionRange( spliced.caret, spliced.caret );
        input.dispatchEvent( new Event( "input", { bubbles: true } ) );
      },
      onError    : reset,
      onCancel   : reset,
    } );
  };
}
