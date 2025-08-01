/**
 * Experimental Progressive TTS Streaming - Firefox-First Implementation
 * 
 * This module implements true progressive audio streaming using sequential
 * audio playback to prevent simultaneous chunk overlap issues.
 * 
 * Key Features:
 * - Sequential Audio Element Queue for proper chunk ordering
 * - Firefox-optimized Web Audio API implementation
 * - Multiple audio elements fallback strategy
 * - Real-time latency measurement
 * - Direct ElevenLabs endpoint connection
 * - No dependencies on existing HybridTTS class
 */

/**
 * Sequential Audio Manager
 * 
 * Manages audio chunks in a queue to ensure sequential playback without overlap.
 * Uses HTML5 audio elements with 'ended' event listeners for reliable timing.
 */
class SequentialAudioManager {
    constructor( onChunkStart = null, onChunkEnd = null, debug = false ) {
        this.chunkQueue = [];
        this.currentlyPlaying = false;
        this.currentAudio = null;
        this.chunksPlayed = 0;
        this.debug = debug;
        
        // Callbacks for external tracking
        this.onChunkStart = onChunkStart;
        this.onChunkEnd = onChunkEnd;
        
        if ( this.debug ) {
            console.log( '[SequentialAudioManager] Initialized' );
        }
    }
    
    addChunk( audioBlob ) {
        this.chunkQueue.push( audioBlob );
        
        if ( this.debug ) {
            console.log( `[SequentialAudioManager] Added chunk to queue (${this.chunkQueue.length} total)` );
        }
        
        // Start playing if not already playing
        if ( !this.currentlyPlaying ) {
            this.playNextChunk();
        }
    }
    
    playNextChunk() {
        // Check if queue is empty
        if ( this.chunkQueue.length === 0 ) {
            this.currentlyPlaying = false;
            this.currentAudio = null;
            
            if ( this.debug ) {
                console.log( '[SequentialAudioManager] Queue empty, playback complete' );
            }
            
            return;
        }
        
        // Get next chunk from queue
        const nextChunk = this.chunkQueue.shift();
        this.chunksPlayed++;
        
        if ( this.debug ) {
            console.log( `[SequentialAudioManager] Playing chunk ${this.chunksPlayed} (${this.chunkQueue.length} remaining)` );
        }
        
        // Create audio element for this chunk
        this.currentAudio = new Audio( URL.createObjectURL( nextChunk ) );
        this.currentlyPlaying = true;
        
        // Set up event handlers
        this.currentAudio.addEventListener( 'ended', () => {
            this.onChunkComplete();
        } );
        
        this.currentAudio.addEventListener( 'error', ( e ) => {
            console.error( '[SequentialAudioManager] Audio playback error:', e.target.error );
            this.onChunkComplete(); // Continue to next chunk even on error
        } );
        
        // Notify external callback
        if ( this.onChunkStart ) {
            this.onChunkStart( this.chunksPlayed );
        }
        
        // Start playback
        const playPromise = this.currentAudio.play();
        if ( playPromise !== undefined ) {
            playPromise.catch( ( error ) => {
                console.error( '[SequentialAudioManager] Play promise rejected:', error );
                this.onChunkComplete(); // Continue to next chunk
            } );
        }
    }
    
    onChunkComplete() {
        if ( this.debug ) {
            console.log( `[SequentialAudioManager] Chunk ${this.chunksPlayed} completed` );
        }
        
        // Clean up current audio
        if ( this.currentAudio ) {
            URL.revokeObjectURL( this.currentAudio.src );
            this.currentAudio = null;
        }
        
        // Notify external callback
        if ( this.onChunkEnd ) {
            this.onChunkEnd( this.chunksPlayed );
        }
        
        // Play next chunk
        this.playNextChunk();
    }
    
    stop() {
        if ( this.debug ) {
            console.log( '[SequentialAudioManager] Stopping playback' );
        }
        
        // Clear queue
        this.chunkQueue = [];
        
        // Stop current audio
        if ( this.currentAudio && !this.currentAudio.paused ) {
            this.currentAudio.pause();
            URL.revokeObjectURL( this.currentAudio.src );
        }
        
        this.currentlyPlaying = false;
        this.currentAudio = null;
    }
    
    reset() {
        this.stop();
        this.chunksPlayed = 0;
        
        if ( this.debug ) {
            console.log( '[SequentialAudioManager] Reset complete' );
        }
    }
}

class ExperimentalProgressiveTTS {
    constructor() {
        // Firefox-first configuration
        this.isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
        this.sessionId = null;
        this.websocket = null;
        this.audioContext = null;
        this.useWebAudioAPI = false;
        
        // Progressive playback state
        this.isStreaming = false;
        this.startTime = null;
        this.firstAudioTime = null;
        this.chunksReceived = 0;
        this.chunksPlayed = 0;
        this.currentPlaybackTime = 0;
        
        // Audio elements pool for fallback (kept for Web Audio API compatibility)
        this.audioElements = [];
        this.audioElementIndex = 0;
        this.maxAudioElements = 5;
        
        // Sequential Audio Manager for proper chunk ordering
        this.sequentialAudioManager = null;
        
        // Metrics tracking
        this.latencyMeasurements = [];
        this.chunkTimings = [];
        
        // UI elements
        this.logElement = null;
        this.statusElements = {};
        
        this.initialize();
    }
    
    async initialize() {
        this.log('🦊 Initializing Firefox-First Progressive TTS', 'info');
        
        // Get UI elements
        this.logElement = document.getElementById('console-log');
        this.setupStatusElements();
        
        // Detect browser and capabilities
        this.detectBrowserCapabilities();
        
        // Initialize audio system
        await this.initializeAudioSystem();
        
        // Initialize sequential audio manager
        this.initializeSequentialAudioManager();
        
        // Get session ID
        await this.getSessionId();
        
        this.log('✅ Experimental Progressive TTS initialized successfully', 'success');
        this.updateStatus('playback-status', 'Ready');
    }
    
    setupStatusElements() {
        this.statusElements = {
            browserInfo: document.getElementById('browser-info'),
            sessionId: document.getElementById('session-id'),
            websocketStatus: document.getElementById('websocket-status'),
            audioContextStatus: document.getElementById('audio-context-status'),
            firstAudioLatency: document.getElementById('first-audio-latency'),
            chunksReceived: document.getElementById('chunks-received'),
            chunksPlayed: document.getElementById('chunks-played'),
            totalDuration: document.getElementById('total-duration'),
            playbackStatus: document.getElementById('playback-status'),
            audioMethod: document.getElementById('audio-method')
        };
    }
    
    detectBrowserCapabilities() {
        const userAgent = navigator.userAgent;
        let browserInfo = 'Unknown';
        
        if (this.isFirefox) {
            const firefoxMatch = userAgent.match(/Firefox\/(\d+)/);
            const version = firefoxMatch ? firefoxMatch[1] : 'Unknown';
            browserInfo = `🦊 Firefox ${version}`;
            
            // Show Firefox badge
            const badge = document.getElementById('firefox-badge');
            if (badge) {
                badge.style.background = '#ff9500';
                badge.textContent = 'Firefox Detected ✓';
            }
        } else {
            browserInfo = userAgent.split(' ')[0];
            
            // Show browser warning for non-Firefox
            const warning = document.getElementById('browser-warning');
            if (warning) {
                warning.style.display = 'block';
            }
            
            this.log('⚠️ Non-Firefox browser detected - some features may not work optimally', 'warning');
        }
        
        this.updateStatus('browserInfo', browserInfo);
        this.log(`Browser detected: ${browserInfo}`, 'info');
        
        // Check Web Audio API support
        const hasWebAudio = !!(window.AudioContext || window.webkitAudioContext);
        this.log(`Web Audio API support: ${hasWebAudio ? '✓' : '✗'}`, hasWebAudio ? 'success' : 'error');
        
        // Check WebSocket support
        const hasWebSocket = !!window.WebSocket;
        this.log(`WebSocket support: ${hasWebSocket ? '✓' : '✗'}`, hasWebSocket ? 'success' : 'error');
    }
    
    async initializeAudioSystem() {
        try {
            // Try to initialize Web Audio API (Firefox-optimized)
            if (window.AudioContext || window.webkitAudioContext) {
                // Don't create AudioContext until user interaction (autoplay policy)
                this.log('🎵 Web Audio API available - will initialize on user interaction', 'info');
                this.updateStatus('audioContextStatus', 'Available (pending user interaction)');
                this.updateStatus('audioMethod', 'Web Audio API (preferred)');
                this.useWebAudioAPI = true;
            } else {
                this.log('⚠️ Web Audio API not available - using audio elements fallback', 'warning');
                this.updateStatus('audioContextStatus', 'Not available');
                this.updateStatus('audioMethod', 'Audio Elements (fallback)');
                this.useWebAudioAPI = false;
            }
            
            // Initialize audio elements pool for fallback
            this.initializeAudioElementsPool();
            
        } catch (error) {
            this.log(`❌ Audio system initialization failed: ${error.message}`, 'error');
            this.updateStatus('audioContextStatus', 'Failed');
        }
    }
    
    initializeAudioElementsPool() {
        this.log(`🔊 Creating ${this.maxAudioElements} audio elements for seamless playback`, 'info');
        
        for (let i = 0; i < this.maxAudioElements; i++) {
            const audio = document.createElement('audio');
            audio.style.display = 'none';
            audio.preload = 'auto';
            
            // Firefox-specific optimizations
            if (this.isFirefox) {
                audio.mozAudioChannelType = 'content';
                audio.mozPreservesPitch = false; // Disable pitch correction for faster processing
            }
            
            // Error handling
            audio.addEventListener('error', (e) => {
                this.log(`❌ Audio element ${i} error: ${e.target.error?.message || 'Unknown error'}`, 'error');
            });
            
            // Track when audio starts playing
            audio.addEventListener('play', () => {
                this.onAudioChunkPlayStart(i);
            });
            
            // Track when audio ends
            audio.addEventListener('ended', () => {
                this.onAudioChunkPlayEnd(i);
            });
            
            document.body.appendChild(audio);
            this.audioElements.push(audio);
        }
    }
    
    initializeSequentialAudioManager() {
        this.log( '🎯 Initializing Sequential Audio Manager for proper chunk ordering', 'info' );
        
        // Create sequential audio manager with callbacks for metrics tracking
        this.sequentialAudioManager = new SequentialAudioManager(
            // onChunkStart callback
            ( chunkIndex ) => {
                this.chunksPlayed++;
                this.updateStatus( 'chunksPlayed', this.chunksPlayed );
                this.log( `🎵 Sequential chunk ${chunkIndex} started playing`, 'success' );
            },
            // onChunkEnd callback
            ( chunkIndex ) => {
                this.log( `⏹️ Sequential chunk ${chunkIndex} completed`, 'info' );
            },
            // debug flag
            true
        );
        
        this.updateStatus( 'audioMethod', 'Sequential Audio Elements (fixed)' );
        this.log( '✅ Sequential Audio Manager initialized successfully', 'success' );
    }
    
    async getSessionId() {
        try {
            this.log('🔗 Getting session ID...', 'info');
            const response = await fetch('/api/get-session-id');
            const data = await response.json();
            this.sessionId = data.session_id;
            
            this.updateStatus('sessionId', this.sessionId);
            this.log(`✅ Session ID obtained: ${this.sessionId}`, 'success');
            
        } catch (error) {
            this.log(`❌ Failed to get session ID: ${error.message}`, 'error');
            throw error;
        }
    }
    
    async initializeWebAudioContext() {
        if (!this.useWebAudioAPI || this.audioContext) return;
        
        try {
            // Create AudioContext (Firefox-optimized)
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                // Firefox-specific optimizations
                latencyHint: 'interactive', // Optimize for low latency
                sampleRate: 44100 // Standard sample rate
            });
            
            // Handle suspended state (autoplay policy)
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }
            
            this.currentPlaybackTime = this.audioContext.currentTime;
            this.updateStatus('audioContextStatus', `Initialized (${this.audioContext.sampleRate}Hz)`);
            this.log(`🎵 Web Audio API initialized - Sample rate: ${this.audioContext.sampleRate}Hz`, 'success');
            
        } catch (error) {
            this.log(`❌ Web Audio API initialization failed: ${error.message}`, 'error');
            this.useWebAudioAPI = false;
            this.updateStatus('audioMethod', 'Audio Elements (Web Audio failed)');
            throw error;
        }
    }
    
    async connectWebSocket() {
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.log('⚠️ WebSocket already connected', 'warning');
            return;
        }
        
        try {
            this.log('🔌 Connecting to WebSocket...', 'info');
            
            const wsUrl = `ws://${window.location.host}/ws/audio/${encodeURIComponent(this.sessionId)}`;
            this.websocket = new WebSocket(wsUrl);
            
            this.websocket.onopen = () => {
                this.log('✅ WebSocket connected successfully', 'success');
                this.updateStatus('websocketStatus', 'Connected');
            };
            
            this.websocket.onclose = () => {
                this.log('📡 WebSocket disconnected', 'info');
                this.updateStatus('websocketStatus', 'Disconnected');
            };
            
            this.websocket.onerror = (error) => {
                this.log(`❌ WebSocket error: ${error}`, 'error');
                this.updateStatus('websocketStatus', 'Error');
            };
            
            this.websocket.onmessage = (event) => {
                this.handleWebSocketMessage(event);
            };
            
            // Wait for connection
            await new Promise((resolve, reject) => {
                this.websocket.onopen = resolve;
                this.websocket.onerror = reject;
                
                // Timeout after 5 seconds
                setTimeout(() => reject(new Error('WebSocket connection timeout')), 5000);
            });
            
        } catch (error) {
            this.log(`❌ WebSocket connection failed: ${error.message}`, 'error');
            throw error;
        }
    }
    
    async handleWebSocketMessage(event) {
        if (event.data instanceof Blob) {
            // Binary audio chunk received
            await this.handleAudioChunk(event.data);
        } else {
            // Text message (status update)
            try {
                const message = JSON.parse(event.data);
                this.handleStatusMessage(message);
            } catch (e) {
                this.log(`📨 Non-JSON message received: ${event.data}`, 'info');
            }
        }
    }
    
    async handleAudioChunk(audioBlob) {
        this.chunksReceived++;
        this.updateStatus('chunksReceived', this.chunksReceived);
        
        // Record first chunk timing
        if (this.chunksReceived === 1 && this.startTime) {
            this.firstAudioTime = Date.now();
            const latency = this.firstAudioTime - this.startTime;
            this.updateStatus('firstAudioLatency', `${latency}ms`);
            this.latencyMeasurements.push(latency);
            
            if (latency < 500) {
                this.log(`🚀 EXCELLENT! First audio in ${latency}ms (target: <500ms)`, 'success');
            } else {
                this.log(`⚠️ First audio in ${latency}ms (target: <500ms)`, 'warning');
            }
        }
        
        // Add chunk indicator to UI
        this.addChunkIndicator();
        
        // Add chunk to sequential audio manager for proper ordering
        if ( this.sequentialAudioManager ) {
            this.sequentialAudioManager.addChunk( audioBlob );
            this.log( `📦 Audio chunk ${this.chunksReceived} added to sequential queue`, 'info' );
        } else {
            this.log( '❌ Sequential Audio Manager not initialized!', 'error' );
            // Fallback to immediate playback (should not happen)
            if ( this.useWebAudioAPI && this.audioContext ) {
                await this.playChunkWithWebAudio( audioBlob );
            } else {
                await this.playChunkWithAudioElement( audioBlob );
            }
        }
    }
    
    async playChunkWithWebAudio(audioBlob) {
        try {
            // Convert blob to ArrayBuffer
            const arrayBuffer = await audioBlob.arrayBuffer();
            
            // Decode audio data
            const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
            
            // Create buffer source
            const source = this.audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(this.audioContext.destination);
            
            // Schedule for immediate playback
            const playTime = Math.max(this.audioContext.currentTime, this.currentPlaybackTime);
            source.start(playTime);
            
            // Update playback time for next chunk
            this.currentPlaybackTime = playTime + audioBuffer.duration;
            
            this.chunksPlayed++;
            this.updateStatus('chunksPlayed', this.chunksPlayed);
            
            this.log(`🎵 Chunk ${this.chunksPlayed} playing via Web Audio API (duration: ${audioBuffer.duration.toFixed(2)}s)`, 'success');
            
        } catch (error) {
            this.log(`❌ Web Audio playback failed: ${error.message}`, 'error');
            // Fallback to audio element
            await this.playChunkWithAudioElement(audioBlob);
        }
    }
    
    async playChunkWithAudioElement(audioBlob) {
        try {
            // Get next audio element from pool
            const audio = this.audioElements[this.audioElementIndex % this.maxAudioElements];
            this.audioElementIndex++;
            
            // Create object URL for blob
            const audioUrl = URL.createObjectURL(audioBlob);
            audio.src = audioUrl;
            
            // Attempt to play immediately
            const playPromise = audio.play();
            
            if (playPromise !== undefined) {
                await playPromise;
                this.chunksPlayed++;
                this.updateStatus('chunksPlayed', this.chunksPlayed);
                this.log(`🔊 Chunk ${this.chunksPlayed} playing via Audio Element`, 'success');
                
                // Clean up URL after playing
                audio.addEventListener('ended', () => {
                    URL.revokeObjectURL(audioUrl);
                }, { once: true });
                
            } else {
                this.log('⚠️ Audio play() returned undefined', 'warning');
            }
            
        } catch (error) {
            if (error.name === 'NotAllowedError') {
                this.log('🔒 Autoplay prevented - user interaction required', 'warning');
            } else {
                this.log(`❌ Audio element playback failed: ${error.message}`, 'error');
            }
        }
    }
    
    handleStatusMessage(message) {
        const { type, text, status, provider } = message;
        
        switch (type) {
            case 'status':
                if (status === 'loading') {
                    this.log(`📡 ${text} (${provider})`, 'info');
                    this.updateStatus('playbackStatus', 'Loading...');
                } else if (status === 'streaming') {
                    this.log(`🚀 ${text} (${provider})`, 'success');
                    this.updateStatus('playbackStatus', 'Streaming');
                }
                break;
                
            case 'audio_complete':
            case 'audio_streaming_complete':
                this.log(`✅ ${text} (${provider})`, 'success');
                this.onStreamComplete();
                break;
                
            case 'error':
                this.log(`❌ ${text} (${provider})`, 'error');
                this.updateStatus('playbackStatus', 'Error');
                this.isStreaming = false;
                break;
                
            default:
                this.log(`📨 ${type}: ${text}`, 'info');
        }
    }
    
    onStreamComplete() {
        this.isStreaming = false;
        this.updateStatus('playbackStatus', 'Complete');
        
        if (this.startTime) {
            const totalTime = Date.now() - this.startTime;
            this.updateStatus('totalDuration', `${(totalTime / 1000).toFixed(1)}s`);
            this.log(`🏁 Streaming complete - Total time: ${(totalTime / 1000).toFixed(1)}s`, 'success');
        }
        
        // Enable test button
        const testBtn = document.getElementById('test-progressive-btn');
        if (testBtn) {
            testBtn.disabled = false;
            testBtn.textContent = '🚀 Test Progressive Streaming';
        }
    }
    
    onAudioChunkPlayStart(elementIndex) {
        this.log(`▶️ Audio element ${elementIndex} started playing`, 'info');
    }
    
    onAudioChunkPlayEnd(elementIndex) {
        this.log(`⏹️ Audio element ${elementIndex} finished playing`, 'info');
    }
    
    addChunkIndicator() {
        const chunksDisplay = document.getElementById('chunks-display');
        if (!chunksDisplay) return;
        
        const indicator = document.createElement('div');
        indicator.className = 'chunk-indicator';
        indicator.title = `Chunk ${this.chunksReceived} - ${new Date().toLocaleTimeString()}`;
        
        chunksDisplay.appendChild(indicator);
        
        // Auto-scroll to show latest chunk
        chunksDisplay.scrollTop = chunksDisplay.scrollHeight;
        
        // Add latency bar to chart
        this.addLatencyBar();
    }
    
    addLatencyBar() {
        const chart = document.getElementById('latency-chart');
        if (!chart || this.latencyMeasurements.length === 0) return;
        
        const latency = this.latencyMeasurements[this.latencyMeasurements.length - 1];
        const maxLatency = 3000; // 3 seconds max for chart scale
        const heightPercent = Math.min((latency / maxLatency) * 100, 100);
        
        const bar = document.createElement('div');
        bar.className = 'latency-bar';
        bar.style.height = `${heightPercent}%`;
        bar.style.left = `${this.latencyMeasurements.length * 12}px`;
        bar.title = `${latency}ms`;
        
        // Color based on performance
        if (latency < 500) {
            bar.style.background = 'linear-gradient(to top, #4caf50, #81c784)'; // Green
        } else if (latency < 1000) {
            bar.style.background = 'linear-gradient(to top, #ff9800, #ffb74d)'; // Orange
        } else {
            bar.style.background = 'linear-gradient(to top, #f44336, #e57373)'; // Red
        }
        
        chart.appendChild(bar);
    }
    
    async testProgressiveStreaming() {
        const textInput = document.getElementById('test-text');
        const testBtn = document.getElementById('test-progressive-btn');
        
        if (!textInput || !testBtn) {
            this.log('❌ UI elements not found', 'error');
            return;
        }
        
        const text = textInput.value.trim();
        if (!text) {
            this.log('⚠️ Please enter text to test', 'warning');
            return;
        }
        
        try {
            // Disable test button
            testBtn.disabled = true;
            testBtn.textContent = '🔄 Testing...';
            
            // Reset metrics
            this.resetMetrics();
            
            // Initialize Web Audio Context on user interaction
            if (this.useWebAudioAPI) {
                await this.initializeWebAudioContext();
            }
            
            // Connect WebSocket
            await this.connectWebSocket();
            
            this.log(`🚀 Starting progressive streaming test: "${text}"`, 'success');
            this.isStreaming = true;
            this.startTime = Date.now();
            this.updateStatus('playbackStatus', 'Requesting...');
            
            // Get current UI settings
            const settings = getCurrentSettings();
            
            // Send TTS request to ElevenLabs endpoint
            const response = await fetch('/api/get-speech-elevenlabs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com'
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    text: text,
                    ...settings
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            this.log('📡 Request sent successfully - waiting for audio chunks...', 'success');
            
        } catch (error) {
            this.log(`❌ Test failed: ${error.message}`, 'error');
            this.isStreaming = false;
            testBtn.disabled = false;
            testBtn.textContent = '🚀 Test Progressive Streaming';
            this.updateStatus('playbackStatus', 'Error');
        }
    }
    
    async testABComparison() {
        const textInput = document.getElementById('test-text');
        const text = textInput?.value.trim();
        
        if (!text) {
            this.log('⚠️ Please enter text to test', 'warning');
            return;
        }
        
        this.log('⚖️ Starting A/B Comparison: Flash vs Turbo models', 'info');
        
        // Test 1: Flash v2.5 (Balanced Profile)
        this.log('🔵 Testing Flash v2.5 (Balanced Profile)...', 'info');
        await this.runSingleTest(text, {
            model_id: 'eleven_flash_v2_5',
            quality_profile: 'balanced'
        }, 'Flash v2.5');
        
        // Wait between tests
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        // Test 2: Turbo v2.5 (Quality Profile)
        this.log('🔴 Testing Turbo v2.5 (Quality Profile)...', 'info');
        await this.runSingleTest(text, {
            model_id: 'eleven_turbo_v2_5',
            quality_profile: 'quality'
        }, 'Turbo v2.5');
        
        this.log('✅ A/B Comparison Complete! Check logs above for latency comparison.', 'success');
    }
    
    async runSingleTest(text, settings, modelName) {
        try {
            // Reset metrics for this test
            this.resetMetrics();
            
            // Initialize if needed
            if (this.useWebAudioAPI) {
                await this.initializeWebAudioContext();
            }
            
            // Connect WebSocket
            await this.connectWebSocket();
            
            this.isStreaming = true;
            this.startTime = Date.now();
            this.updateStatus('playbackStatus', `Testing ${modelName}...`);
            
            // Send TTS request with specific settings
            const response = await fetch('/api/get-speech-elevenlabs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com'
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    text: text,
                    ...settings
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            // Wait for completion (max 10 seconds)
            const testTimeout = setTimeout(() => {
                this.isStreaming = false;
                this.log(`⏰ ${modelName} test timeout after 10 seconds`, 'warning');
            }, 10000);
            
            // Wait for streaming to complete
            while (this.isStreaming && Date.now() - this.startTime < 10000) {
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            
            clearTimeout(testTimeout);
            
            // Log results
            const totalTime = Date.now() - this.startTime;
            const firstAudioLatency = this.firstAudioTime ? (this.firstAudioTime - this.startTime) : 'N/A';
            
            this.log(`📊 ${modelName} Results: First Audio: ${firstAudioLatency}ms, Total: ${totalTime}ms, Chunks: ${this.chunksReceived}`, 'success');
            
            // Close WebSocket
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                this.websocket.close();
            }
            
        } catch (error) {
            this.log(`❌ ${modelName} test failed: ${error.message}`, 'error');
            this.isStreaming = false;
        }
    }
    
    resetMetrics() {
        this.chunksReceived = 0;
        this.chunksPlayed = 0;
        this.currentPlaybackTime = this.audioContext ? this.audioContext.currentTime : 0;
        this.startTime = null;
        this.firstAudioTime = null;
        this.chunkTimings = [];
        
        this.updateStatus('chunksReceived', 0);
        this.updateStatus('chunksPlayed', 0);
        this.updateStatus('firstAudioLatency', '-');
        this.updateStatus('totalDuration', '-');
        
        // Clear chunk indicators
        const chunksDisplay = document.getElementById('chunks-display');
        if (chunksDisplay) {
            chunksDisplay.innerHTML = '';
        }
        
        // Clear latency chart
        const chart = document.getElementById('latency-chart');
        if (chart) {
            chart.innerHTML = '';
        }
        
        this.latencyMeasurements = [];
        
        // Reset sequential audio manager
        if ( this.sequentialAudioManager ) {
            this.sequentialAudioManager.reset();
            this.log( '🔄 Sequential Audio Manager reset', 'info' );
        }
    }
    
    stopStreaming() {
        this.log('⏹️ Stopping streaming...', 'info');
        this.isStreaming = false;
        
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.websocket.close();
        }
        
        // Stop sequential audio manager
        if ( this.sequentialAudioManager ) {
            this.sequentialAudioManager.stop();
            this.log( '⏹️ Sequential Audio Manager stopped', 'info' );
        }
        
        // Stop all audio elements (fallback pool)
        this.audioElements.forEach((audio, index) => {
            if (!audio.paused) {
                audio.pause();
                this.log(`⏸️ Stopped audio element ${index}`, 'info');
            }
        });
        
        // Enable test button
        const testBtn = document.getElementById('test-progressive-btn');
        if (testBtn) {
            testBtn.disabled = false;
            testBtn.textContent = '🚀 Test Progressive Streaming';
        }
        
        this.updateStatus('playbackStatus', 'Stopped');
    }
    
    updateStatus(elementId, value) {
        const element = this.statusElements[elementId];
        if (element) {
            element.textContent = value;
        }
    }
    
    log(message, type = 'info') {
        if (!this.logElement) return;
        
        const timestamp = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        
        logEntry.innerHTML = `<span class="timestamp">[${timestamp}]</span> <span class="${type}">${message}</span>`;
        
        this.logElement.appendChild(logEntry);
        this.logElement.scrollTop = this.logElement.scrollHeight;
        
        // Also log to browser console for debugging
        console.log(`[ExperimentalTTS] ${message}`);
    }
    
    clearLogs() {
        if (this.logElement) {
            this.logElement.innerHTML = '';
            this.log('📝 Console cleared', 'info');
        }
    }
}

// Test message presets
const testMessages = {
    short: "Testing progressive streaming with a short message.",
    medium: "This is a comprehensive test of progressive TTS streaming with ElevenLabs to validate immediate audio playback capabilities in Firefox.",
    long: "This is an extended test message designed to validate progressive text-to-speech streaming capabilities using ElevenLabs WebSocket API with Firefox-optimized Web Audio API implementation. The purpose is to measure latency from text input to first audio output, ensuring chunks play immediately as they arrive rather than waiting for complete audio generation. This approach should demonstrate significant performance improvements over traditional collect-then-play strategies, with target latency under 500 milliseconds for the first audio chunk and seamless playback continuity between subsequent chunks.",
    custom: "Enter your own test message here to experiment with progressive streaming..."
};

function setTestText(preset) {
    const textInput = document.getElementById('test-text');
    if (textInput && testMessages[preset]) {
        textInput.value = testMessages[preset];
        
        // Focus on textarea for immediate editing
        textInput.focus();
        
        if (preset !== 'custom') {
            textInput.select();
        }
    }
}

function testProgressiveStreaming() {
    if (window.experimentalTTS) {
        window.experimentalTTS.testProgressiveStreaming();
    }
}

function stopStreaming() {
    if (window.experimentalTTS) {
        window.experimentalTTS.stopStreaming();
    }
}

function clearLogs() {
    if (window.experimentalTTS) {
        window.experimentalTTS.clearLogs();
    }
}

// A/B Testing Functions
function testABComparison() {
    if (window.experimentalTTS) {
        window.experimentalTTS.testABComparison();
    }
}

function updateCustomSettings() {
    const profileSelect = document.getElementById('profile-select');
    const customSettings = document.getElementById('custom-settings');
    const modelSelect = document.getElementById('model-select');
    
    if (profileSelect.value === 'custom') {
        customSettings.style.display = 'block';
    } else {
        customSettings.style.display = 'none';
        
        // Update model based on profile
        switch(profileSelect.value) {
            case 'balanced':
            case 'fast':
                modelSelect.value = 'eleven_flash_v2_5';
                break;
            case 'quality':
                modelSelect.value = 'eleven_turbo_v2_5';
                break;
        }
    }
}

function getCurrentSettings() {
    const profileSelect = document.getElementById('profile-select');
    const modelSelect = document.getElementById('model-select');
    const voiceSelect = document.getElementById('voice-select');
    
    const baseSettings = {
        model_id: modelSelect.value,
        voice_id: voiceSelect.value
    };
    
    if (profileSelect.value === 'custom') {
        return {
            ...baseSettings,
            quality_profile: 'custom',
            stability: parseFloat(document.getElementById('stability-input').value),
            similarity_boost: parseFloat(document.getElementById('similarity-input').value),
            style: parseFloat(document.getElementById('style-input').value),
            speed: parseFloat(document.getElementById('speed-input').value),
            use_speaker_boost: document.getElementById('speaker-boost-input').checked
        };
    } else {
        return {
            ...baseSettings,
            quality_profile: profileSelect.value
        };
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.experimentalTTS = new ExperimentalProgressiveTTS();
});