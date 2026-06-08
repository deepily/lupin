/**
 * Chunk Sequencing Test Laboratory - ElevenLabs Audio Order Fix
 * 
 * This module provides side-by-side comparison testing of:
 * 1. Original Method: Direct chunk playback (current experimental TTS approach)
 * 2. Sequenced Method: Buffered and ordered chunk playback (new approach)
 * 
 * Purpose: Validate chunk sequencing fixes without breaking existing functionality
 */

class ChunkSequencer {
    constructor(method = 'sequenced') {
        this.method = method;
        this.expectedSequence = 0;
        this.chunkBuffer = new Map(); // sequence -> {chunk, timestamp, played}
        this.playbackQueue = [];
        this.lastPlayTime = 0;
        this.missingChunkTimeout = 2000; // 2 seconds timeout for missing chunks
        this.timeouts = new Map(); // sequence -> timeout handle
        
        // Metrics tracking
        this.startTime = null;
        this.firstAudioTime = null;
        this.chunksReceived = 0;
        this.chunksPlayed = 0;
        this.orderIssues = 0;
        this.chunkTimings = [];
        
        // Audio system
        this.audioContext = null;
        this.audioElements = [];
        this.audioElementIndex = 0;
        this.maxAudioElements = 5;
        this.useWebAudioAPI = false;
        
        // WebSocket
        this.websocket = null;
        this.sessionId = null;
        this.isStreaming = false;
        
        // UI elements
        this.logElement = null;
        this.statusElements = {};
        this.chunkDisplays = {};
        
        this.initialize();
    }
    
    async initialize() {
        this.log(`🔧 Initializing ${this.method} method handler`, 'info');
        
        // Get UI elements
        this.logElement = document.getElementById('console-log');
        this.setupStatusElements();
        
        // Initialize audio system
        await this.initializeAudioSystem();
        
        // Get session ID
        await this.getSessionId();
        
        this.log(`✅ ${this.method} method handler initialized successfully`, 'success');
    }
    
    setupStatusElements() {
        const prefix = this.method;
        this.statusElements = {
            status: document.getElementById(`${prefix}-status`),
            firstAudio: document.getElementById(`${prefix}-first-audio`),
            totalTime: document.getElementById(`${prefix}-total-time`),
            chunkCount: document.getElementById(`${prefix}-chunk-count`),
            orderIssues: document.getElementById(`${prefix}-order-issues`)
        };
        
        this.chunkDisplays = {
            received: document.getElementById(`${prefix}-chunks-received`),
            played: document.getElementById(`${prefix}-chunks-played`)
        };
    }
    
    async initializeAudioSystem() {
        try {
            // Check Web Audio API support
            if (window.AudioContext || window.webkitAudioContext) {
                this.useWebAudioAPI = true;
                this.log(`🎵 Web Audio API available for ${this.method} method`, 'info');
            } else {
                this.useWebAudioAPI = false;
                this.log(`⚠️ Web Audio API not available for ${this.method} method - using audio elements`, 'warning');
            }
            
            // Initialize audio elements pool
            this.initializeAudioElementsPool();
            
        } catch (error) {
            this.log(`❌ Audio system initialization failed for ${this.method}: ${error.message}`, 'error');
        }
    }
    
    initializeAudioElementsPool() {
        this.log(`🔊 Creating ${this.maxAudioElements} audio elements for ${this.method} method`, 'info');
        
        for (let i = 0; i < this.maxAudioElements; i++) {
            const audio = document.createElement('audio');
            audio.style.display = 'none';
            audio.preload = 'auto';
            
            // Error handling
            audio.addEventListener('error', (e) => {
                this.log(`❌ ${this.method} audio element ${i} error: ${e.target.error?.message || 'Unknown error'}`, 'error');
            });
            
            // Track playback events
            audio.addEventListener('play', () => {
                this.onAudioChunkPlayStart(i);
            });
            
            audio.addEventListener('ended', () => {
                this.onAudioChunkPlayEnd(i);
            });
            
            document.body.appendChild(audio);
            this.audioElements.push(audio);
        }
    }
    
    async getSessionId() {
        try {
            const response = await fetch('/api/get-session-id');
            const data = await response.json();
            this.sessionId = data.session_id;
            this.log(`✅ Session ID obtained for ${this.method}: ${this.sessionId}`, 'success');
        } catch (error) {
            this.log(`❌ Failed to get session ID for ${this.method}: ${error.message}`, 'error');
            throw error;
        }
    }
    
    async initializeWebAudioContext() {
        if (!this.useWebAudioAPI || this.audioContext) return;
        
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                latencyHint: 'interactive',
                sampleRate: 44100
            });
            
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }
            
            this.lastPlayTime = this.audioContext.currentTime;
            this.log(`🎵 Web Audio API initialized for ${this.method} - Sample rate: ${this.audioContext.sampleRate}Hz`, 'success');
            
        } catch (error) {
            this.log(`❌ Web Audio API initialization failed for ${this.method}: ${error.message}`, 'error');
            this.useWebAudioAPI = false;
            throw error;
        }
    }
    
    async connectWebSocket() {
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.log(`⚠️ WebSocket already connected for ${this.method}`, 'warning');
            return;
        }
        
        try {
            this.log(`🔌 Connecting WebSocket for ${this.method} method...`, 'info');
            
            const wsUrl = `ws://${window.location.host}/ws/audio/${encodeURIComponent(this.sessionId)}`;
            this.websocket = new WebSocket(wsUrl);
            
            this.websocket.onopen = () => {
                this.log(`✅ WebSocket connected successfully for ${this.method}`, 'success');
                this.updateStatus('status', `Connected (${this.method})`);
            };
            
            this.websocket.onclose = () => {
                this.log(`📡 WebSocket disconnected for ${this.method}`, 'info');
                this.updateStatus('status', `Disconnected (${this.method})`);
            };
            
            this.websocket.onerror = (error) => {
                this.log(`❌ WebSocket error for ${this.method}: ${error}`, 'error');
                this.updateStatus('status', `Error (${this.method})`);
            };
            
            this.websocket.onmessage = (event) => {
                this.handleWebSocketMessage(event);
            };
            
            // Wait for connection
            await new Promise((resolve, reject) => {
                this.websocket.onopen = resolve;
                this.websocket.onerror = reject;
                setTimeout(() => reject(new Error('WebSocket connection timeout')), 5000);
            });
            
        } catch (error) {
            this.log(`❌ WebSocket connection failed for ${this.method}: ${error.message}`, 'error');
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
                this.log(`📨 Non-JSON message received for ${this.method}: ${event.data}`, 'info');
            }
        }
    }
    
    async handleAudioChunk(audioBlob) {
        const sequence = this.chunksReceived; // Simple sequential numbering
        this.chunksReceived++;
        
        // Record first chunk timing
        if (this.chunksReceived === 1 && this.startTime) {
            this.firstAudioTime = Date.now();
            const latency = this.firstAudioTime - this.startTime;
            this.updateStatus('firstAudio', `${latency}ms`);
            
            if (latency < 500) {
                this.log(`🚀 ${this.method.toUpperCase()} - First audio in ${latency}ms (EXCELLENT!)`, 'success');
            } else {
                this.log(`⚠️ ${this.method.toUpperCase()} - First audio in ${latency}ms (target: <500ms)`, 'warning');
            }
        }
        
        // Add chunk indicator to UI
        this.addChunkIndicator('received', sequence);
        this.updateStatus('chunkCount', this.chunksReceived);
        
        // Handle chunk based on method
        if (this.method === 'original') {
            // Original method: Play immediately (current behavior)
            await this.playChunkImmediately(audioBlob, sequence);
        } else {
            // Sequenced method: Buffer and order chunks
            await this.bufferAndSequenceChunk(audioBlob, sequence);
        }
    }
    
    async playChunkImmediately(audioBlob, sequence) {
        // This mimics the current experimental TTS behavior
        this.log(`🔶 ${this.method.toUpperCase()} - Playing chunk ${sequence} immediately`, 'info');
        
        if (this.useWebAudioAPI && this.audioContext) {
            await this.playChunkWithWebAudio(audioBlob, sequence);
        } else {
            await this.playChunkWithAudioElement(audioBlob, sequence);
        }
        
        this.chunksPlayed++;
        this.addChunkIndicator('played', sequence);
        this.updateStatus('chunkCount', `${this.chunksReceived}/${this.chunksPlayed}`);
    }
    
    async bufferAndSequenceChunk(audioBlob, sequence) {
        this.log(`🔷 ${this.method.toUpperCase()} - Buffering chunk ${sequence} for sequenced playback`, 'info');
        
        // Add to buffer
        this.chunkBuffer.set(sequence, {
            chunk: audioBlob,
            timestamp: Date.now(),
            played: false
        });
        
        // Set timeout for missing chunks
        this.setMissingChunkTimeout(sequence);
        
        // Process any consecutive chunks we can play
        await this.processBufferedChunks();
    }
    
    setMissingChunkTimeout(sequence) {
        // Clear any existing timeout for this sequence
        if (this.timeouts.has(sequence)) {
            clearTimeout(this.timeouts.get(sequence));
        }
        
        // Set new timeout
        const timeoutHandle = setTimeout(() => {
            this.log(`⏰ ${this.method.toUpperCase()} - Timeout waiting for chunk ${sequence}`, 'warning');
            this.handleMissingChunk(sequence);
        }, this.missingChunkTimeout);
        
        this.timeouts.set(sequence, timeoutHandle);
    }
    
    async processBufferedChunks() {
        // Play consecutive chunks starting from expected sequence
        while (this.chunkBuffer.has(this.expectedSequence)) {
            const chunkData = this.chunkBuffer.get(this.expectedSequence);
            
            if (!chunkData.played) {
                this.log(`▶️ ${this.method.toUpperCase()} - Playing buffered chunk ${this.expectedSequence} in order`, 'success');
                
                // Clear timeout for this chunk
                if (this.timeouts.has(this.expectedSequence)) {
                    clearTimeout(this.timeouts.get(this.expectedSequence));
                    this.timeouts.delete(this.expectedSequence);
                }
                
                // Play the chunk
                if (this.useWebAudioAPI && this.audioContext) {
                    await this.playChunkWithWebAudio(chunkData.chunk, this.expectedSequence);
                } else {
                    await this.playChunkWithAudioElement(chunkData.chunk, this.expectedSequence);
                }
                
                // Mark as played
                chunkData.played = true;
                this.chunksPlayed++;
                this.addChunkIndicator('played', this.expectedSequence);
                this.updateStatus('chunkCount', `${this.chunksReceived}/${this.chunksPlayed}`);
            }
            
            this.expectedSequence++;
        }
    }
    
    handleMissingChunk(sequence) {
        this.log(`❌ ${this.method.toUpperCase()} - Missing chunk ${sequence}, marking as order issue`, 'error');
        this.orderIssues++;
        this.updateStatus('orderIssues', this.orderIssues);
        
        // Skip this chunk and try to continue
        if (sequence === this.expectedSequence) {
            this.expectedSequence++;
            // Try to process any subsequent chunks
            this.processBufferedChunks();
        }
    }
    
    async playChunkWithWebAudio(audioBlob, sequence) {
        try {
            const arrayBuffer = await audioBlob.arrayBuffer();
            const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
            
            const source = this.audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(this.audioContext.destination);
            
            // Improved scheduling for sequenced method
            let playTime;
            if (this.method === 'sequenced') {
                playTime = Math.max(this.audioContext.currentTime, this.lastPlayTime);
                this.lastPlayTime = playTime + audioBuffer.duration;
            } else {
                // Original method timing
                playTime = Math.max(this.audioContext.currentTime, this.lastPlayTime);
                this.lastPlayTime = playTime + audioBuffer.duration;
            }
            
            source.start(playTime);
            
            this.log(`🎵 ${this.method.toUpperCase()} - Chunk ${sequence} playing via Web Audio API (duration: ${audioBuffer.duration.toFixed(2)}s)`, 'success');
            
        } catch (error) {
            this.log(`❌ ${this.method.toUpperCase()} - Web Audio playback failed for chunk ${sequence}: ${error.message}`, 'error');
            // Fallback to audio element
            await this.playChunkWithAudioElement(audioBlob, sequence);
        }
    }
    
    async playChunkWithAudioElement(audioBlob, sequence) {
        try {
            const audio = this.audioElements[this.audioElementIndex % this.maxAudioElements];
            this.audioElementIndex++;
            
            const audioUrl = URL.createObjectURL(audioBlob);
            audio.src = audioUrl;
            
            const playPromise = audio.play();
            
            if (playPromise !== undefined) {
                await playPromise;
                this.log(`🔊 ${this.method.toUpperCase()} - Chunk ${sequence} playing via Audio Element`, 'success');
                
                audio.addEventListener('ended', () => {
                    URL.revokeObjectURL(audioUrl);
                }, { once: true });
            }
            
        } catch (error) {
            if (error.name === 'NotAllowedError') {
                this.log(`🔒 ${this.method.toUpperCase()} - Autoplay prevented for chunk ${sequence}`, 'warning');
            } else {
                this.log(`❌ ${this.method.toUpperCase()} - Audio element playback failed for chunk ${sequence}: ${error.message}`, 'error');
            }
        }
    }
    
    handleStatusMessage(message) {
        const { type, text, status, provider } = message;
        
        switch (type) {
            case 'audio_streaming_status':
                if (status === 'loading') {
                    this.log(`📡 ${this.method.toUpperCase()} - ${text}`, 'info');
                    this.updateStatus('status', `Loading (${this.method})`);
                } else if (status === 'streaming') {
                    this.log(`🚀 ${this.method.toUpperCase()} - ${text}`, 'success');
                    this.updateStatus('status', `Streaming (${this.method})`);
                }
                break;
                
            case 'audio_streaming_complete':
                this.log(`✅ ${this.method.toUpperCase()} - ${text}`, 'success');
                this.onStreamComplete();
                break;
                
            case 'error':
                this.log(`❌ ${this.method.toUpperCase()} - ${text}`, 'error');
                this.updateStatus('status', `Error (${this.method})`);
                this.isStreaming = false;
                break;
                
            default:
                this.log(`📨 ${this.method.toUpperCase()} - ${type}: ${text}`, 'info');
        }
    }
    
    onStreamComplete() {
        this.isStreaming = false;
        this.updateStatus('status', `Complete (${this.method})`);
        
        if (this.startTime) {
            const totalTime = Date.now() - this.startTime;
            this.updateStatus('totalTime', `${(totalTime / 1000).toFixed(1)}s`);
            this.log(`🏁 ${this.method.toUpperCase()} - Streaming complete - Total time: ${(totalTime / 1000).toFixed(1)}s`, 'success');
        }
        
        // Final order validation for sequenced method
        if (this.method === 'sequenced') {
            this.validateFinalOrder();
        }
    }
    
    validateFinalOrder() {
        // Check if all chunks were played in order
        let orderCorrect = true;
        for (let i = 0; i < this.chunksReceived; i++) {
            if (!this.chunkBuffer.has(i) || !this.chunkBuffer.get(i).played) {
                orderCorrect = false;
                break;
            }
        }
        
        if (orderCorrect && this.orderIssues === 0) {
            this.log(`✅ ${this.method.toUpperCase()} - All chunks played in correct order!`, 'success');
        } else {
            this.log(`⚠️ ${this.method.toUpperCase()} - Order issues detected: ${this.orderIssues}`, 'warning');
        }
    }
    
    onAudioChunkPlayStart(elementIndex) {
        this.log(`▶️ ${this.method.toUpperCase()} - Audio element ${elementIndex} started playing`, 'info');
    }
    
    onAudioChunkPlayEnd(elementIndex) {
        this.log(`⏹️ ${this.method.toUpperCase()} - Audio element ${elementIndex} finished playing`, 'info');
    }
    
    addChunkIndicator(type, sequence) {
        const display = this.chunkDisplays[type];
        if (!display) return;
        
        const indicator = document.createElement('div');
        indicator.className = `chunk-indicator chunk-${type}`;
        indicator.textContent = sequence.toString();
        indicator.title = `${type.charAt(0).toUpperCase() + type.slice(1)} chunk ${sequence} - ${new Date().toLocaleTimeString()}`;
        
        display.appendChild(indicator);
        display.scrollTop = display.scrollHeight;
    }
    
    async testWithSettings(settings) {
        try {
            // Reset metrics
            this.resetMetrics();
            
            // Initialize Web Audio Context on user interaction
            if (this.useWebAudioAPI) {
                await this.initializeWebAudioContext();
            }
            
            // Connect WebSocket
            await this.connectWebSocket();
            
            this.log(`🚀 ${this.method.toUpperCase()} - Starting test with settings: ${JSON.stringify(settings)}`, 'success');
            this.isStreaming = true;
            this.startTime = Date.now();
            this.updateStatus('status', `Testing (${this.method})`);
            
            // Send TTS request to ElevenLabs endpoint
            const response = await fetch('/api/get-speech-elevenlabs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com'
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    text: settings.text,
                    voice_id: settings.voice_id,
                    model_id: settings.model_id,
                    quality_profile: settings.quality_profile
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            this.log(`📡 ${this.method.toUpperCase()} - Request sent successfully - waiting for audio chunks...`, 'success');
            
        } catch (error) {
            this.log(`❌ ${this.method.toUpperCase()} - Test failed: ${error.message}`, 'error');
            this.isStreaming = false;
            this.updateStatus('status', `Error (${this.method})`);
            throw error;
        }
    }
    
    resetMetrics() {
        this.expectedSequence = 0;
        this.chunkBuffer.clear();
        this.chunksReceived = 0;
        this.chunksPlayed = 0;
        this.orderIssues = 0;
        this.startTime = null;
        this.firstAudioTime = null;
        this.chunkTimings = [];
        this.lastPlayTime = this.audioContext ? this.audioContext.currentTime : 0;
        
        // Clear timeouts
        this.timeouts.forEach(timeout => clearTimeout(timeout));
        this.timeouts.clear();
        
        // Reset UI
        this.updateStatus('firstAudio', '-');
        this.updateStatus('totalTime', '-');
        this.updateStatus('chunkCount', '0');
        this.updateStatus('orderIssues', '0');
        
        // Clear chunk displays
        Object.values(this.chunkDisplays).forEach(display => {
            if (display) display.innerHTML = '';
        });
    }
    
    stopStreaming() {
        this.log(`⏹️ ${this.method.toUpperCase()} - Stopping streaming...`, 'info');
        this.isStreaming = false;
        
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.websocket.close();
        }
        
        // Stop all audio elements
        this.audioElements.forEach((audio, index) => {
            if (!audio.paused) {
                audio.pause();
                this.log(`⏸️ ${this.method.toUpperCase()} - Stopped audio element ${index}`, 'info');
            }
        });
        
        this.updateStatus('status', `Stopped (${this.method})`);
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
        console.log(`[ChunkSequencer-${this.method}] ${message}`);
    }
}

// Global test instances
let originalHandler = null;
let sequencedHandler = null;

// Initialize handlers when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
    try {
        originalHandler = new ChunkSequencer('original');
        sequencedHandler = new ChunkSequencer('sequenced');
        
        // Give them time to initialize
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        console.log('✅ Chunk Sequencing Test Laboratory initialized successfully');
        
    } catch (error) {
        console.error('❌ Failed to initialize Chunk Sequencing Test Laboratory:', error);
    }
});

// Test functions
async function runComparisonTest() {
    const settings = getCurrentSettings();
    
    if (!settings.text) {
        alert('Please enter text to test');
        return;
    }
    
    try {
        console.log('🔬 Starting A/B Comparison Test...');
        
        // Test original method first
        console.log('📊 Testing Original Method...');
        await originalHandler.testWithSettings(settings);
        
        // Wait a moment between tests
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Test sequenced method
        console.log('🎯 Testing Sequenced Method...');
        await sequencedHandler.testWithSettings(settings);
        
        console.log('✅ A/B Comparison Test initiated - monitor both panels for results');
        
    } catch (error) {
        console.error('❌ Comparison test failed:', error);
        alert(`Comparison test failed: ${error.message}`);
    }
}

async function testOriginalMethod() {
    const settings = getCurrentSettings();
    
    if (!settings.text) {
        alert('Please enter text to test');
        return;
    }
    
    try {
        await originalHandler.testWithSettings(settings);
    } catch (error) {
        alert(`Original method test failed: ${error.message}`);
    }
}

async function testSequencedMethod() {
    const settings = getCurrentSettings();
    
    if (!settings.text) {
        alert('Please enter text to test');
        return;
    }
    
    try {
        await sequencedHandler.testWithSettings(settings);
    } catch (error) {
        alert(`Sequenced method test failed: ${error.message}`);
    }
}

function stopAllTests() {
    if (originalHandler) {
        originalHandler.stopStreaming();
    }
    
    if (sequencedHandler) {
        sequencedHandler.stopStreaming();
    }
    
    console.log('⏹️ All tests stopped');
}

function clearLogs() {
    const logElement = document.getElementById('console-log');
    if (logElement) {
        logElement.innerHTML = '';
        logElement.innerHTML = `
            <span class="timestamp">[${new Date().toLocaleTimeString()}]</span> <span class="info">Console cleared</span>
            <span class="timestamp">[Info]</span> <span class="info">Ready for new tests</span>
        `;
    }
}

function getCurrentSettings() {
    return {
        text: document.getElementById('test-text')?.value.trim() || '',
        voice_id: document.getElementById('voice-select')?.value || '21m00Tcm4TlvDq8ikWAM',
        model_id: document.getElementById('model-select')?.value || 'eleven_flash_v2_5', 
        quality_profile: document.getElementById('profile-select')?.value || 'balanced'
    };
}