/**
 * AudioRecorder - Reusable audio recording module with server-side transcription
 *
 * Records audio from microphone, converts to MP3, and uploads to FastAPI endpoint
 * for Whisper-based transcription.
 *
 * Usage:
 *   const recorder = new AudioRecorder({
 *       uploadEndpoint: '/api/upload-and-transcribe-mp3',
 *       authToken: 'your-bearer-token',
 *       onTranscription: (text) => console.log('Transcribed:', text),
 *       onError: (error) => console.error('Error:', error)
 *   });
 *
 *   await recorder.startRecording();  // Start recording
 *   await recorder.stopRecording();   // Stop and auto-upload
 */

class AudioRecorder {
    constructor( options = {} ) {
        // Audio settings
        this.audioFormat   = options.audioFormat || 'audio/mpeg';
        this.maxDuration   = options.maxDuration || 30000;  // 30 seconds default (Whisper limit)

        // Upload configuration
        this.uploadEndpoint = options.uploadEndpoint || '/api/upload-and-transcribe-mp3';
        this.uploadMethod   = options.uploadMethod || 'POST';
        this.authToken      = options.authToken || null;

        // Callbacks
        this.onRecordingStart = options.onRecordingStart || null;
        this.onRecordingStop  = options.onRecordingStop || null;
        this.onTranscription  = options.onTranscription || null;
        this.onError          = options.onError || null;

        // Debug
        this.debug   = options.debug || false;
        this.verbose = options.verbose || false;

        // Internal state
        this._state         = 'idle';  // 'idle', 'recording', 'processing', 'error'
        this._cancelling    = false;   // Flag to prevent upload when cancelled
        this._mediaRecorder = null;
        this._mediaStream   = null;
        this._audioChunks   = [];
        this._startTime     = null;
        this._durationInterval = null;
        this._maxDurationTimeout = null;

        // Performance metrics (for debugging)
        this._metrics = {
            recordingStartTime   : null,
            recordingStopTime    : null,
            base64StartTime      : null,
            base64CompleteTime   : null,
            uploadStartTime      : null,
            uploadCompleteTime   : null
        };
    }

    /**
     * Start recording audio from microphone
     *
     * Requires:
     *   - User grants microphone permission
     *   - MediaRecorder API supported
     *
     * Ensures:
     *   - Recording state active
     *   - onRecordingStart callback triggered
     *   - Duration counter started
     */
    async startRecording() {
        if ( this._state === 'recording' ) {
            this.log( 'Already recording, ignoring start request' );
            return;
        }

        try {
            this.log( 'Requesting microphone access...' );

            // Request microphone permission
            this._mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

            // Check MediaRecorder support
            if ( !window.MediaRecorder ) {
                throw new Error( 'MediaRecorder API not supported in this browser' );
            }

            // Create MediaRecorder with format preference
            const mimeType = this._getBestMimeType();
            this.log( `Using audio format: ${mimeType}` );

            this._mediaRecorder = new MediaRecorder( this._mediaStream, { mimeType } );
            this._audioChunks = [];

            // Collect audio data chunks
            this._mediaRecorder.addEventListener( 'dataavailable', ( event ) => {
                if ( event.data.size > 0 ) {
                    this._audioChunks.push( event.data );
                    this.log( `Audio chunk received: ${event.data.size} bytes` );
                }
            } );

            // Handle recording stop
            this._mediaRecorder.addEventListener( 'stop', () => {
                this.log( 'MediaRecorder stopped' );
                this._handleRecordingStopped();
            } );

            // Handle errors
            this._mediaRecorder.addEventListener( 'error', ( event ) => {
                this.error( `MediaRecorder error: ${event.error}` );
                this._handleError({
                    type: 'recorder_error',
                    message: `Recording failed: ${event.error}`,
                    originalError: event.error
                });
            } );

            // Start recording
            this._mediaRecorder.start();
            this._state = 'recording';
            this._startTime = Date.now();
            this._metrics.recordingStartTime = performance.now();

            // Start max duration timeout
            this._maxDurationTimeout = setTimeout( () => {
                this.log( `Max duration (${this.maxDuration}ms) reached, stopping recording` );
                this.stopRecording();
            }, this.maxDuration );

            // Trigger callback
            if ( this.onRecordingStart ) {
                this.onRecordingStart();
            }

            this.log( 'Recording started successfully' );

        } catch ( error ) {
            this.error( `Failed to start recording: ${error}` );

            let errorType = 'unknown_error';
            let errorMessage = 'Could not start recording';

            if ( error.name === 'NotAllowedError' ) {
                errorType = 'permission_denied';
                errorMessage = 'Microphone permission denied. Please allow access and try again.';
            } else if ( error.name === 'NotFoundError' ) {
                errorType = 'no_microphone';
                errorMessage = 'No microphone found. Please connect a microphone and try again.';
            } else if ( error.name === 'NotSupportedError' ) {
                errorType = 'not_supported';
                errorMessage = 'Audio recording not supported in this browser.';
            }

            this._handleError({
                type: errorType,
                message: errorMessage,
                originalError: error
            });

            this._cleanup();
        }
    }

    /**
     * Stop recording and upload for transcription
     *
     * Ensures:
     *   - Recording stopped
     *   - Audio uploaded to server
     *   - onTranscription callback triggered with result
     */
    async stopRecording() {
        if ( this._state !== 'recording' ) {
            this.log( 'Not recording, ignoring stop request' );
            return;
        }

        this.log( 'Stopping recording...' );

        // Clear max duration timeout
        if ( this._maxDurationTimeout ) {
            clearTimeout( this._maxDurationTimeout );
            this._maxDurationTimeout = null;
        }

        // Stop the media recorder
        if ( this._mediaRecorder && this._mediaRecorder.state !== 'inactive' ) {
            this._mediaRecorder.stop();
        }
    }

    /**
     * Handle recording stopped event (internal)
     */
    async _handleRecordingStopped() {
        // Check if recording was cancelled (recorder may be null if cleanup already ran)
        if ( this._cancelling || !this._mediaRecorder ) {
            this.log( 'Recording cancelled, skipping upload' );
            return;
        }

        this._state = 'processing';
        this._metrics.recordingStopTime = performance.now();

        // Create audio blob
        const mimeType = this._mediaRecorder.mimeType;
        const audioBlob = new Blob( this._audioChunks, { type: mimeType } );

        this.log( `Audio blob created: ${audioBlob.size} bytes, type: ${mimeType}` );

        // Trigger stop callback
        if ( this.onRecordingStop ) {
            this.onRecordingStop( audioBlob );
        }

        // Validate recording
        if ( audioBlob.size === 0 ) {
            this._handleError({
                type: 'empty_recording',
                message: 'Recording is empty. Please try again and speak into the microphone.',
                originalError: null
            });
            this._cleanup();
            return;
        }

        // Upload and transcribe
        await this._uploadAndTranscribe( audioBlob );
    }

    /**
     * Upload audio blob to server and trigger transcription
     */
    async _uploadAndTranscribe( audioBlob ) {
        try {
            this.log( `Uploading audio to ${this.uploadEndpoint}...` );

            // Convert blob to base64
            this._metrics.base64StartTime = performance.now();
            const base64Audio = await this._blobToBase64( audioBlob );
            const base64Data = base64Audio.split( ',' )[1];  // Remove data:audio/mpeg;base64, prefix
            this._metrics.base64CompleteTime = performance.now();

            // Prepare headers
            const headers = {
                'Content-Type': audioBlob.type
            };

            if ( this.authToken ) {
                headers['Authorization'] = `Bearer ${this.authToken}`;
            }

            // Upload to FastAPI endpoint
            this._metrics.uploadStartTime = performance.now();
            const response = await fetch( this.uploadEndpoint, {
                method: this.uploadMethod,
                headers: headers,
                body: base64Data
            } );

            if ( !response.ok ) {
                const errorText = await response.text();
                throw new Error( `Server error: ${response.status} ${response.statusText}. ${errorText}` );
            }

            const result = await response.json();
            this._metrics.uploadCompleteTime = performance.now();
            this.log( 'Transcription response:', result );

            // Extract transcription text (prefer processed transcription over raw)
            const transcription = result.transcription || result.text || '';

            if ( !transcription ) {
                throw new Error( 'No transcription returned from server' );
            }

            this.log( `Transcription complete: "${transcription}"` );

            // Log performance metrics (debug mode only)
            if ( this.debug ) {
                const recordingDuration = this._metrics.recordingStopTime - this._metrics.recordingStartTime;
                const base64Duration = this._metrics.base64CompleteTime - this._metrics.base64StartTime;
                const uploadDuration = this._metrics.uploadCompleteTime - this._metrics.uploadStartTime;
                const totalRoundTrip = this._metrics.uploadCompleteTime - this._metrics.recordingStartTime;

                console.log( '[AudioRecorder] Performance Metrics:' );
                console.log( `  Recording duration:   ${(recordingDuration / 1000).toFixed(1)}s` );
                console.log( `  Base64 conversion:    ${Math.round(base64Duration)}ms` );
                console.log( `  Upload + transcribe:  ${Math.round(uploadDuration)}ms` );
                console.log( `  Total round-trip:     ${(totalRoundTrip / 1000).toFixed(2)}s` );
            }

            // Trigger transcription callback
            if ( this.onTranscription ) {
                this.onTranscription( transcription );
            }

            // Cleanup
            this._cleanup();
            this._state = 'idle';

        } catch ( error ) {
            this.error( `Upload/transcription failed: ${error}` );

            this._handleError({
                type: 'upload_failed',
                message: `Voice input failed: ${error.message}`,
                originalError: error
            });

            this._cleanup();
        }
    }

    /**
     * Convert Blob to base64 data URL
     */
    _blobToBase64( blob ) {
        return new Promise( ( resolve, reject ) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve( reader.result );
            reader.onerror = reject;
            reader.readAsDataURL( blob );
        } );
    }

    /**
     * Get best supported MIME type for audio recording
     */
    _getBestMimeType() {
        const types = [
            'audio/mpeg',   // MP3 (preferred, matches backend)
            'audio/webm',   // WebM (fallback)
            'audio/ogg',    // Ogg (fallback)
            'audio/wav'     // WAV (fallback)
        ];

        for ( const type of types ) {
            if ( MediaRecorder.isTypeSupported( type ) ) {
                return type;
            }
        }

        // Fallback to browser default
        return '';
    }

    /**
     * Handle error and trigger callback
     */
    _handleError( error ) {
        this._state = 'error';

        if ( this.onError ) {
            this.onError( error );
        }
    }

    /**
     * Cleanup resources
     */
    _cleanup() {
        // Stop all media stream tracks
        if ( this._mediaStream ) {
            this._mediaStream.getTracks().forEach( track => track.stop() );
            this._mediaStream = null;
        }

        // Clear timeouts
        if ( this._durationInterval ) {
            clearInterval( this._durationInterval );
            this._durationInterval = null;
        }

        if ( this._maxDurationTimeout ) {
            clearTimeout( this._maxDurationTimeout );
            this._maxDurationTimeout = null;
        }

        // Reset state
        this._mediaRecorder = null;
        this._audioChunks = [];
        this._startTime = null;
        this._cancelling = false;
    }

    /**
     * Destroy recorder and cleanup all resources
     */
    destroy() {
        this.log( 'Destroying AudioRecorder...' );

        if ( this._state === 'recording' ) {
            this.stopRecording();
        }

        this._cleanup();
        this._state = 'idle';
    }

    // ========================================
    // STATE INSPECTION
    // ========================================

    /**
     * Check if currently recording
     */
    get isRecording() {
        return this._state === 'recording';
    }

    /**
     * Check if processing (uploading/transcribing)
     */
    get isProcessing() {
        return this._state === 'processing';
    }

    /**
     * Get current recording duration in milliseconds
     */
    get recordingDuration() {
        if ( !this._startTime ) {
            return 0;
        }
        return Date.now() - this._startTime;
    }

    /**
     * Get recording statistics
     */
    getStats() {
        return {
            state: this._state,
            duration: this.recordingDuration,
            chunksRecorded: this._audioChunks.length,
            isRecording: this.isRecording,
            isProcessing: this.isProcessing
        };
    }

    // ========================================
    // LOGGING
    // ========================================

    log( ...args ) {
        if ( this.debug ) {
            console.log( '[AudioRecorder]', ...args );
        }
    }

    error( ...args ) {
        if ( this.debug ) {
            console.error( '[AudioRecorder]', ...args );
        }
    }
}

// ========================================
// EXPORTS (UMD Pattern)
// ========================================

// Browser global (script tag)
if ( typeof window !== 'undefined' ) {
    window.AudioRecorder = AudioRecorder;
}

// CommonJS (Node.js, testing)
if ( typeof module !== 'undefined' && typeof module.exports !== 'undefined' ) {
    module.exports = AudioRecorder;
}

// ES6 export (future-proofing)
try {
    if ( typeof exports !== 'undefined' ) {
        exports.AudioRecorder = AudioRecorder;
    }
} catch ( e ) {
    // ES6 export not supported, ignore
}
