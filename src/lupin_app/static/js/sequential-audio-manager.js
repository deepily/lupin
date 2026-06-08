/**
 * Sequential Audio Manager
 * 
 * Production-ready utility for managing audio chunks in a queue to ensure 
 * sequential playback without overlap. Uses HTML5 audio elements with 'ended' 
 * event listeners for reliable timing.
 * 
 * Features:
 * - Queue-based sequential playback 
 * - Firefox-optimized implementation
 * - Enhanced error recovery and memory management
 * - Configurable logging and callbacks
 * - Production-grade performance optimization
 * 
 * Usage:
 *   const manager = new SequentialAudioManager( onStart, onEnd, debug );
 *   manager.addChunk( audioBlob );
 */

class SequentialAudioManager {
    constructor( onChunkStart = null, onChunkEnd = null, debug = false ) {
        // Core state management
        this.chunkQueue = [];
        this.currentlyPlaying = false;
        this.currentAudio = null;
        this.chunksPlayed = 0;
        this.debug = debug;
        
        // Callbacks for external tracking
        this.onChunkStart = onChunkStart;
        this.onChunkEnd = onChunkEnd;
        
        // Production enhancements
        this.maxQueueSize = 100; // Prevent memory issues with very long streams
        this.retryAttempts = 3;  // Retry failed chunks
        this.retryDelay = 100;   // MS delay between retries
        this.cleanupDelay = 50;  // MS delay for blob URL cleanup
        
        // Memory management tracking
        this.blobUrls = new Set(); // Track blob URLs for proper cleanup
        this.totalChunksProcessed = 0;
        this.errorCount = 0;
        
        // Browser optimization detection
        this.isFirefox = navigator.userAgent.toLowerCase().includes( 'firefox' );
        this.supportsPromiseBasedPlay = 'play' in HTMLAudioElement.prototype;
        
        if ( this.debug ) {
            console.log( '[SequentialAudioManager] Initialized with production enhancements' );
            console.log( `[SequentialAudioManager] Browser: ${this.isFirefox ? 'Firefox' : 'Other'}, Promise-based play: ${this.supportsPromiseBasedPlay}` );
        }
    }
    
    /**
     * Add an audio chunk to the playback queue
     * 
     * @param {Blob} audioBlob - Audio data as a Blob object
     * @returns {boolean} - True if chunk was added, false if queue is full
     */
    addChunk( audioBlob ) {
        // Production enhancement: Prevent memory issues with oversized queues
        if ( this.chunkQueue.length >= this.maxQueueSize ) {
            console.warn( `[SequentialAudioManager] Queue size limit reached (${this.maxQueueSize}), dropping oldest chunk` );
            this._cleanupOldestChunk();
        }
        
        // Validate input
        if ( !audioBlob || !(audioBlob instanceof Blob) ) {
            console.error( '[SequentialAudioManager] Invalid audio chunk provided' );
            return false;
        }
        
        this.chunkQueue.push( audioBlob );
        
        if ( this.debug ) {
            console.log( `[SequentialAudioManager] Added chunk to queue (${this.chunkQueue.length} total)` );
        }
        
        // Start playing if not already playing
        if ( !this.currentlyPlaying ) {
            this.playNextChunk();
        }
        
        return true;
    }
    
    /**
     * Play the next chunk in the queue
     * 
     * @private
     */
    playNextChunk() {
        // Check if queue is empty
        if ( this.chunkQueue.length === 0 ) {
            this.currentlyPlaying = false;
            this.currentAudio = null;
            
            if ( this.debug ) {
                console.log( '[SequentialAudioManager] Queue empty, playback complete' );
                console.log( `[SequentialAudioManager] Total processed: ${this.totalChunksProcessed}, Errors: ${this.errorCount}` );
            }
            
            return;
        }
        
        // Get next chunk from queue
        const nextChunk = this.chunkQueue.shift();
        this.chunksPlayed++;
        this.totalChunksProcessed++;
        
        if ( this.debug ) {
            console.log( `[SequentialAudioManager] Playing chunk ${this.chunksPlayed} (${this.chunkQueue.length} remaining)` );
        }
        
        // Create blob URL and track for cleanup
        const blobUrl = URL.createObjectURL( nextChunk );
        this.blobUrls.add( blobUrl );
        
        // Create audio element for this chunk
        this.currentAudio = new Audio( blobUrl );
        this.currentlyPlaying = true;
        
        // Set up event handlers with enhanced error recovery
        this.currentAudio.addEventListener( 'ended', () => {
            this.onChunkComplete();
        } );
        
        this.currentAudio.addEventListener( 'error', ( e ) => {
            this.errorCount++;
            console.error( '[SequentialAudioManager] Audio playbook error:', e.target.error );
            
            // Enhanced error logging for production debugging
            if ( this.debug ) {
                console.error( '[SequentialAudioManager] Error details:', {
                    chunksPlayed: this.chunksPlayed,
                    queueLength: this.chunkQueue.length,
                    errorCode: e.target.error?.code,
                    errorMessage: e.target.error?.message,
                    audioSrc: e.target.src?.substring( 0, 50 ) + '...'
                } );
            }
            
            this.onChunkComplete(); // Continue to next chunk even on error
        } );
        
        // Firefox-specific optimizations
        if ( this.isFirefox ) {
            this.currentAudio.preload = 'auto';
            this.currentAudio.volume = 1.0; // Ensure full volume for Firefox
        }
        
        // Notify external callback
        if ( this.onChunkStart ) {
            try {
                this.onChunkStart( this.chunksPlayed );
            } catch ( error ) {
                console.error( '[SequentialAudioManager] Error in onChunkStart callback:', error );
            }
        }
        
        // Start playbook with enhanced promise handling
        this._playWithRetry( this.currentAudio, 0 );
    }
    
    /**
     * Play audio with retry logic for production reliability
     * 
     * @private
     * @param {HTMLAudioElement} audioElement - Audio element to play
     * @param {number} attemptNumber - Current retry attempt (0-based)
     */
    _playWithRetry( audioElement, attemptNumber ) {
        const playPromise = audioElement.play();
        
        if ( this.supportsPromiseBasedPlay && playPromise !== undefined ) {
            playPromise.catch( ( error ) => {
                if ( attemptNumber < this.retryAttempts ) {
                    console.warn( `[SequentialAudioManager] Play failed (attempt ${attemptNumber + 1}), retrying in ${this.retryDelay}ms:`, error );
                    
                    setTimeout( () => {
                        if ( this.currentAudio === audioElement ) { // Ensure we're still the current audio
                            this._playWithRetry( audioElement, attemptNumber + 1 );
                        }
                    }, this.retryDelay );
                } else {
                    console.error( `[SequentialAudioManager] Play failed after ${this.retryAttempts} attempts:`, error );
                    this.onChunkComplete(); // Continue to next chunk
                }
            } );
        }
    }
    
    /**
     * Handle completion of current chunk and continue to next
     * 
     * @private
     */
    onChunkComplete() {
        if ( this.debug ) {
            console.log( `[SequentialAudioManager] Chunk ${this.chunksPlayed} completed` );
        }
        
        // Enhanced cleanup with proper memory management
        if ( this.currentAudio ) {
            const blobUrl = this.currentAudio.src;
            
            // Clean up blob URL with slight delay for browser optimization
            setTimeout( () => {
                if ( this.blobUrls.has( blobUrl ) ) {
                    URL.revokeObjectURL( blobUrl );
                    this.blobUrls.delete( blobUrl );
                    
                    if ( this.debug ) {
                        console.log( `[SequentialAudioManager] Cleaned up blob URL, ${this.blobUrls.size} remaining` );
                    }
                }
            }, this.cleanupDelay );
            
            this.currentAudio = null;
        }
        
        // Notify external callback with error handling
        if ( this.onChunkEnd ) {
            try {
                this.onChunkEnd( this.chunksPlayed );
            } catch ( error ) {
                console.error( '[SequentialAudioManager] Error in onChunkEnd callback:', error );
            }
        }
        
        // Play next chunk
        this.playNextChunk();
    }
    
    /**
     * Stop playbook and clear queue
     */
    stop() {
        if ( this.debug ) {
            console.log( '[SequentialAudioManager] Stopping playbook' );
        }
        
        // Clear queue
        this.chunkQueue = [];
        
        // Stop current audio with enhanced cleanup
        if ( this.currentAudio && !this.currentAudio.paused ) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0; // Reset to beginning
        }
        
        this._cleanupCurrentAudio();
        this.currentlyPlaying = false;
    }
    
    /**
     * Reset manager to initial state
     */
    reset() {
        this.stop();
        this.chunksPlayed = 0;
        this.totalChunksProcessed = 0;
        this.errorCount = 0;
        
        // Clean up any remaining blob URLs
        this._cleanupAllBlobUrls();
        
        if ( this.debug ) {
            console.log( '[SequentialAudioManager] Reset complete' );
        }
    }
    
    /**
     * Get current playbook statistics
     * 
     * @returns {Object} Statistics object
     */
    getStats() {
        return {
            chunksPlayed: this.chunksPlayed,
            queueLength: this.chunkQueue.length,
            isPlaying: this.currentlyPlaying,
            totalProcessed: this.totalChunksProcessed,
            errorCount: this.errorCount,
            activeBlobUrls: this.blobUrls.size
        };
    }
    
    /**
     * Check if manager is currently playing audio
     * 
     * @returns {boolean} True if currently playing
     */
    isPlaying() {
        return this.currentlyPlaying;
    }
    
    /**
     * Get current queue length
     * 
     * @returns {number} Number of chunks in queue
     */
    getQueueLength() {
        return this.chunkQueue.length;
    }
    
    // Private helper methods for enhanced memory management
    
    /**
     * Clean up the oldest chunk when queue is full
     * 
     * @private
     */
    _cleanupOldestChunk() {
        if ( this.chunkQueue.length > 0 ) {
            this.chunkQueue.shift(); // Remove oldest chunk
            console.warn( '[SequentialAudioManager] Dropped oldest chunk due to queue size limit' );
        }
    }
    
    /**
     * Clean up current audio element and its blob URL
     * 
     * @private
     */
    _cleanupCurrentAudio() {
        if ( this.currentAudio ) {
            const blobUrl = this.currentAudio.src;
            if ( this.blobUrls.has( blobUrl ) ) {
                URL.revokeObjectURL( blobUrl );
                this.blobUrls.delete( blobUrl );
            }
            this.currentAudio = null;
        }
    }
    
    /**
     * Clean up all tracked blob URLs
     * 
     * @private
     */
    _cleanupAllBlobUrls() {
        this.blobUrls.forEach( url => {
            URL.revokeObjectURL( url );
        } );
        this.blobUrls.clear();
        
        if ( this.debug ) {
            console.log( '[SequentialAudioManager] All blob URLs cleaned up' );
        }
    }
}

// Support direct script inclusion (browser global)
if ( typeof window !== 'undefined' ) {
    window.SequentialAudioManager = SequentialAudioManager;
}

// Support ES6 modules when needed
if ( typeof module !== 'undefined' && typeof module.exports !== 'undefined' ) {
    module.exports = SequentialAudioManager;
}

// Also try ES6 export for module environments
try {
    if ( typeof exports !== 'undefined' ) {
        exports.SequentialAudioManager = SequentialAudioManager;
    }
} catch ( e ) {
    // ES6 export not supported in this environment, ignore
}