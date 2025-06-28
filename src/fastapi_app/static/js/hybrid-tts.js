/**
 * Hybrid TTS Module
 * 
 * This module provides a reusable hybrid text-to-speech functionality
 * that streams audio chunks via WebSocket for speed while playing the
 * complete audio for reliability.
 * 
 * Usage:
 *   const tts = new HybridTTS();
 *   await tts.initialize();
 *   await tts.speak("Hello, world!");
 */

class HybridTTS {
    constructor(options = {}) {
        // Configuration options
        this.wsUrl = options.wsUrl || `ws://${window.location.host}/ws`;
        this.apiUrl = options.apiUrl || '/api/get-audio';
        this.sessionUrl = options.sessionUrl || '/api/get-session-id';
        
        // State management
        this.websocket = null;
        this.sessionId = options.sessionId || null; // Accept sessionId from options
        this.audioChunks = [];
        this.isRequesting = false;
        this.startTime = null;
        
        // Callbacks
        this.onStatusUpdate = options.onStatusUpdate || (() => {});
        this.onProgressUpdate = options.onProgressUpdate || (() => {});
        this.onComplete = options.onComplete || (() => {});
        this.onError = options.onError || (() => {});
        
        // Audio element (can be provided or created)
        this.audioElement = options.audioElement || this.createAudioElement();
        
        // Cache configuration
        this.cacheEnabled = options.cacheEnabled !== false; // Default true
        this.cacheMaxSize = options.cacheMaxSize || 50 * 1024 * 1024; // 50MB default
        this.cacheMaxAge = options.cacheMaxAge || 24 * 60 * 60 * 1000; // 24 hours
        
        // In-memory cache
        this.audioCache = new Map();
        
        // IndexedDB setup
        this.dbName = 'HybridTTSCache';
        this.dbVersion = 1;
        this.db = null;
        
        // Analytics
        this.analytics = {
            totalRequests: 0,
            cacheHits: 0,
            cacheMisses: 0,
            totalCacheSize: 0,
            popularPhrases: new Map() // Track frequency of phrases
        };
        
        // Initialize IndexedDB if caching is enabled
        if (this.cacheEnabled) {
            this.initializeIndexedDB().catch(err => {
                console.warn('HybridTTS: IndexedDB initialization failed, using memory cache only:', err);
            });
        }
    }
    
    createAudioElement() {
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.style.display = 'none';
        document.body.appendChild(audio);
        
        // Add error handler to catch any audio element errors
        audio.addEventListener('error', (e) => {
            console.error('HybridTTS audio element error:', e);
            if (this._currentPromise && this._currentPromise.reject) {
                console.log('Rejecting HybridTTS promise due to audio error');
                this._currentPromise.reject(new Error('Audio playback failed'));
                this._currentPromise = null;
            }
            this.isRequesting = false;
        });
        
        return audio;
    }
    
    async initialize() {
        try {
            // Use provided session ID if available, otherwise get a new one
            if (!this.sessionId) {
                const response = await fetch(this.sessionUrl);
                const data = await response.json();
                this.sessionId = data.session_id;
                console.log(`HybridTTS: Got new session ID: ${this.sessionId}`);
            } else {
                console.log(`HybridTTS: Using provided session ID: ${this.sessionId}`);
            }
            
            // Connect WebSocket
            const wsFullUrl = `${this.wsUrl}/${this.sessionId}`;
            this.websocket = new WebSocket(wsFullUrl);
            
            return new Promise((resolve, reject) => {
                this.websocket.onopen = () => {
                    console.log('HybridTTS: WebSocket connected');
                    resolve();
                };
                
                this.websocket.onerror = (error) => {
                    console.error('HybridTTS: WebSocket error:', error);
                    this.onError('WebSocket connection failed');
                    reject(error);
                };
                
                this.websocket.onclose = () => {
                    console.log('HybridTTS: WebSocket disconnected');
                };
                
                this.websocket.onmessage = this.handleWebSocketMessage.bind(this);
            });
            
        } catch (error) {
            console.error('HybridTTS: Initialization failed:', error);
            this.onError('Failed to initialize TTS');
            throw error;
        }
    }
    
    handleWebSocketMessage(event) {
        if (event.data instanceof Blob) {
            // Audio chunk received
            this.audioChunks.push(event.data);
            
            const elapsed = (Date.now() - this.startTime) / 1000;
            this.onProgressUpdate(`Received ${this.audioChunks.length} chunks in ${elapsed.toFixed(1)}s`);
            
        } else {
            // Status message
            try {
                const message = JSON.parse(event.data);
                console.log('HybridTTS WebSocket message:', message);
                
                if (message.type === 'audio_complete') {
                    // All chunks received - create and play audio
                    this.playCollectedAudio();
                } else if (message.type === 'status') {
                    if (message.status === 'loading' && this.audioChunks.length === 0) {
                        this.onStatusUpdate(message.text, 'loading');
                        this.startTime = Date.now();
                        
                        // If we're still loading after 5 seconds with no chunks, assume failure
                        setTimeout(() => {
                            if (this.audioChunks.length === 0 && this._currentPromise) {
                                console.log('HybridTTS: No audio chunks received after 5s, assuming failure');
                                if (this._currentPromise && this._currentPromise.reject) {
                                    this._currentPromise.reject(new Error('TTS generation failed - no audio received'));
                                    this._currentPromise = null;
                                }
                                this.isRequesting = false;
                                this.resetAudioState();
                            }
                        }, 5000);
                    } else if (message.status === 'error') {
                        console.log('HybridTTS received error status:', message.text);
                        console.log('Current promise before reject:', this._currentPromise);
                        this.onError(message.text);
                        this.resetAudioState();
                        this.isRequesting = false;
                        
                        // Reject the pending promise so the queue can handle the error
                        if (this._currentPromise && this._currentPromise.reject) {
                            console.log('Rejecting HybridTTS promise with error:', message.text);
                            this._currentPromise.reject(new Error(message.text || 'TTS generation failed'));
                            this._currentPromise = null;
                        } else {
                            console.log('No promise to reject!');
                        }
                    }
                } else if (message.type === 'error') {
                    // Handle error type messages too
                    console.log('HybridTTS received error type:', message);
                    if (this._currentPromise && this._currentPromise.reject) {
                        this._currentPromise.reject(new Error(message.text || message.error || 'TTS generation failed'));
                        this._currentPromise = null;
                    }
                    this.isRequesting = false;
                }
            } catch (e) {
                console.error('HybridTTS: Failed to parse WebSocket message:', e);
            }
        }
    }
    
    async playCollectedAudio() {
        if (this.audioChunks.length === 0) {
            this.onError('No audio data received');
            this.isRequesting = false;
            return;
        }

        const totalTime = (Date.now() - this.startTime) / 1000;
        this.onProgressUpdate(`Complete! ${this.audioChunks.length} chunks in ${totalTime.toFixed(1)}s - Playing audio...`);

        // Create single blob from all chunks
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/mpeg' });
        const audioUrl = URL.createObjectURL(audioBlob);

        // Save to cache if we have the text
        if (this._currentText && this.cacheEnabled) {
            const metadata = {
                chunks: this.audioChunks.length,
                duration: totalTime
            };
            await this.saveToCache(this._currentText, audioBlob, metadata);
            this._currentText = null; // Clear after caching
        }

        // Set up and play audio
        this.audioElement.src = audioUrl;
        this.audioElement.style.display = 'block';

        this.audioElement.play().then(() => {
            this.onStatusUpdate(`Audio playing! (${totalTime.toFixed(1)}s total time)`, 'success');
            this.onComplete(audioUrl, totalTime);
        }).catch(e => {
            this.onStatusUpdate(`Audio ready (${totalTime.toFixed(1)}s total time)`, 'success');
            console.log('HybridTTS: Auto-play prevented:', e.message);
            this.onComplete(audioUrl, totalTime);
        });

        // Clean up - but don't revoke if it's cached
        this.audioElement.addEventListener('ended', () => {
            // Only revoke if not in cache (cache manages its own URLs)
            if (!this.audioCache.has(audioUrl)) {
                URL.revokeObjectURL(audioUrl);
            }
            this.resetAudioState();
        }, { once: true });

        this.isRequesting = false;
    }
    
    resetAudioState() {
        this.audioChunks = [];
        this.startTime = null;
        this.onProgressUpdate('');
    }
    
    async speak(text) {
        if (this.isRequesting) {
            this.onStatusUpdate('Request already in progress...', 'loading');
            return Promise.reject(new Error('Request already in progress'));
        }

        if (!this.websocket || !this.sessionId) {
            this.onError('WebSocket not connected');
            return Promise.reject(new Error('WebSocket not connected'));
        }

        // Update analytics
        this.analytics.totalRequests++;
        this.updatePhraseFrequency(text);

        // Check cache first
        const cached = await this.checkCache(text);
        if (cached) {
            console.log('HybridTTS: Cache hit for text:', text.substring(0, 30) + '...');
            this.analytics.cacheHits++;
            
            // Play cached audio
            this.audioElement.src = cached.audioUrl;
            this.audioElement.style.display = 'block';
            
            this.onStatusUpdate('Playing cached audio', 'success');
            
            return this.audioElement.play().then(() => {
                this.onComplete(cached.audioUrl, 0); // 0 time since it's cached
                return { audioUrl: cached.audioUrl, totalTime: 0, cached: true };
            }).catch(e => {
                this.onStatusUpdate('Cached audio ready', 'success');
                console.log('HybridTTS: Auto-play prevented:', e.message);
                this.onComplete(cached.audioUrl, 0);
                return { audioUrl: cached.audioUrl, totalTime: 0, cached: true };
            });
        }
        
        // Cache miss - proceed with normal flow
        this.analytics.cacheMisses++;
        console.log('HybridTTS: Cache miss for text:', text.substring(0, 30) + '...');

        this.isRequesting = true;

        // Reset state
        this.resetAudioState();
        // Don't set empty src as it causes immediate browser error
        if (this.audioElement.src) {
            this.audioElement.removeAttribute('src');
        }
        this.audioElement.style.display = 'none';

        this.onStatusUpdate('Starting hybrid TTS...', 'loading');

        // Store the text for caching after completion
        this._currentText = text;

        try {
            // Send TTS request (will stream chunks via WebSocket)
            const response = await fetch(this.apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    text: text
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Response just confirms request started
            // Audio will arrive via WebSocket
            return new Promise((resolve, reject) => {
                // Store resolve/reject for later use when audio completes
                this._currentPromise = { resolve, reject };
                
                // Add timeout in case server never sends completion/error
                setTimeout(() => {
                    if (this._currentPromise) {
                        console.log('HybridTTS timeout - no response from server');
                        this._currentPromise.reject(new Error('TTS request timed out'));
                        this._currentPromise = null;
                        this.isRequesting = false;
                        this.resetAudioState();
                    }
                }, 10000); // 10 second timeout - shorter for failed TTS
            });
            
        } catch (error) {
            this.onError(`Error: ${error.message}`);
            this.isRequesting = false;
            this.resetAudioState();
            throw error;
        }
    }
    
    // Override onComplete to resolve the promise
    set onComplete(callback) {
        this._onComplete = callback;
    }
    
    get onComplete() {
        return (audioUrl, totalTime) => {
            if (this._onComplete) {
                this._onComplete(audioUrl, totalTime);
            }
            if (this._currentPromise) {
                this._currentPromise.resolve({ audioUrl, totalTime });
                this._currentPromise = null;
            }
        };
    }
    
    // Override onError to reject the promise
    set onError(callback) {
        this._onError = callback;
    }
    
    get onError() {
        return (error) => {
            if (this._onError) {
                this._onError(error);
            }
            if (this._currentPromise) {
                this._currentPromise.reject(new Error(error));
                this._currentPromise = null;
            }
        };
    }
    
    // Clean up method
    destroy() {
        if (this.websocket) {
            this.websocket.close();
        }
        if (this.audioElement && this.audioElement.parentNode) {
            this.audioElement.parentNode.removeChild(this.audioElement);
        }
        this.resetAudioState();
        
        // Clean up cache
        this.audioCache.forEach(entry => {
            URL.revokeObjectURL(entry.audioUrl);
        });
        this.audioCache.clear();
    }
    
    // Cache Methods
    async generateCacheKey(text) {
        const encoder = new TextEncoder();
        const data = encoder.encode(text);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }
    
    async initializeIndexedDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.dbVersion);
            
            request.onerror = () => reject(request.error);
            request.onsuccess = () => {
                this.db = request.result;
                resolve();
            };
            
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('audioCache')) {
                    const store = db.createObjectStore('audioCache', { keyPath: 'key' });
                    store.createIndex('timestamp', 'timestamp', { unique: false });
                }
            };
        });
    }
    
    async checkCache(text) {
        if (!this.cacheEnabled) return null;
        
        const key = await this.generateCacheKey(text);
        
        // Check in-memory first
        if (this.audioCache.has(key)) {
            const cached = this.audioCache.get(key);
            if (!this.isCacheExpired(cached)) {
                return cached;
            } else {
                // Remove expired entry
                this.audioCache.delete(key);
                URL.revokeObjectURL(cached.audioUrl);
            }
        }
        
        // Check IndexedDB
        if (this.db) {
            const cached = await this.getFromIndexedDB(key);
            if (cached && !this.isCacheExpired(cached)) {
                // Recreate blob URL for in-memory cache
                cached.audioUrl = URL.createObjectURL(cached.audioBlob);
                this.audioCache.set(key, cached);
                return cached;
            }
        }
        
        return null;
    }
    
    async saveToCache(text, audioBlob, metadata) {
        if (!this.cacheEnabled) return;
        
        const key = await this.generateCacheKey(text);
        const cacheEntry = {
            key,
            text,
            audioBlob,
            audioUrl: URL.createObjectURL(audioBlob),
            timestamp: Date.now(),
            size: audioBlob.size,
            metadata
        };
        
        // Update analytics
        this.analytics.totalCacheSize += audioBlob.size;
        
        // Save to in-memory cache
        this.audioCache.set(key, cacheEntry);
        
        // Save to IndexedDB
        if (this.db) {
            await this.saveToIndexedDB(key, cacheEntry);
        }
        
        // Manage cache size
        await this.evictOldEntries();
    }
    
    async getFromIndexedDB(key) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['audioCache'], 'readonly');
            const store = transaction.objectStore('audioCache');
            const request = store.get(key);
            
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }
    
    async saveToIndexedDB(key, entry) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['audioCache'], 'readwrite');
            const store = transaction.objectStore('audioCache');
            const request = store.put(entry);
            
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }
    
    isCacheExpired(entry) {
        return Date.now() - entry.timestamp > this.cacheMaxAge;
    }
    
    async evictOldEntries() {
        let totalSize = 0;
        const entries = Array.from(this.audioCache.values());
        
        // Sort by timestamp (oldest first)
        entries.sort((a, b) => a.timestamp - b.timestamp);
        
        // Calculate total size and remove expired entries
        const validEntries = entries.filter(entry => {
            if (this.isCacheExpired(entry)) {
                this.audioCache.delete(entry.key);
                URL.revokeObjectURL(entry.audioUrl);
                this.analytics.totalCacheSize -= entry.size;
                return false;
            }
            totalSize += entry.size;
            return true;
        });
        
        // Remove oldest entries if over size limit
        while (totalSize > this.cacheMaxSize && validEntries.length > 0) {
            const oldest = validEntries.shift();
            this.audioCache.delete(oldest.key);
            URL.revokeObjectURL(oldest.audioUrl);
            totalSize -= oldest.size;
            this.analytics.totalCacheSize -= oldest.size;
            
            // Also remove from IndexedDB
            if (this.db) {
                const transaction = this.db.transaction(['audioCache'], 'readwrite');
                transaction.objectStore('audioCache').delete(oldest.key);
            }
        }
    }
    
    // Analytics Methods
    updatePhraseFrequency(text) {
        const count = this.analytics.popularPhrases.get(text) || 0;
        this.analytics.popularPhrases.set(text, count + 1);
    }
    
    getAnalytics() {
        const hitRate = this.analytics.totalRequests > 0 
            ? (this.analytics.cacheHits / this.analytics.totalRequests * 100).toFixed(2) 
            : 0;
            
        // Get top 10 popular phrases
        const popularPhrases = Array.from(this.analytics.popularPhrases.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10)
            .map(([phrase, count]) => ({
                phrase: phrase.substring(0, 50) + (phrase.length > 50 ? '...' : ''),
                count
            }));
        
        return {
            totalRequests: this.analytics.totalRequests,
            cacheHits: this.analytics.cacheHits,
            cacheMisses: this.analytics.cacheMisses,
            hitRate: `${hitRate}%`,
            totalCacheSize: `${(this.analytics.totalCacheSize / 1024 / 1024).toFixed(2)} MB`,
            cacheEntries: this.audioCache.size,
            popularPhrases
        };
    }
    
    clearCache() {
        // Clear in-memory cache
        this.audioCache.forEach(entry => {
            URL.revokeObjectURL(entry.audioUrl);
        });
        this.audioCache.clear();
        
        // Clear IndexedDB
        if (this.db) {
            const transaction = this.db.transaction(['audioCache'], 'readwrite');
            transaction.objectStore('audioCache').clear();
        }
        
        // Reset cache size in analytics
        this.analytics.totalCacheSize = 0;
        
        console.log('HybridTTS: Cache cleared');
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = HybridTTS;
}