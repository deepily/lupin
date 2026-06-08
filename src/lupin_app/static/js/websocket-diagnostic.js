/**
 * WebSocket Audio Diagnostic Tool
 * 
 * Pure diagnostic tool to analyze WebSocket connections and audio flow.
 * NO FIXES APPLIED - Just observation and logging to identify root causes.
 * 
 * Focuses on detecting:
 * - Multiple WebSocket connections
 * - Audio timing and overlap issues  
 * - Chunk duplication patterns
 * - Connection lifecycle problems
 */

class WebSocketDiagnosticTool {
    constructor() {
        // Connection tracking
        this.sessionId = null;
        this.connections = new Map(); // connectionId -> connection info
        this.connectionCounter = 0;
        this.activeConnections = 0;
        this.duplicateConnections = 0;
        
        // Audio tracking
        this.chunksReceived = 0;
        this.audioElements = new Map(); // elementId -> element info
        this.audioElementCounter = 0;
        this.simultaneousPlayCount = 0;
        this.chunkTimeline = [];
        
        // Timing
        this.startTime = null;
        this.firstAudioTime = null;
        
        // State
        this.isRunning = false;
        
        // UI elements
        this.logElement = null;
        this.statusElements = {};
        
        this.initialize();
    }
    
    async initialize() {
        this.log('🔧 Initializing WebSocket Diagnostic Tool', 'diagnostic');
        
        // Get UI elements
        this.logElement = document.getElementById('diagnostic-console');
        this.setupStatusElements();
        
        // Get session ID
        await this.getSessionId();
        
        this.log('✅ WebSocket Diagnostic Tool initialized successfully', 'success');
        this.updateStatus('session-id', this.sessionId);
    }
    
    setupStatusElements() {
        this.statusElements = {
            sessionId: document.getElementById('session-id'),
            activeConnections: document.getElementById('active-connections'),
            totalConnections: document.getElementById('total-connections'),
            duplicateConnections: document.getElementById('duplicate-connections'),
            chunksReceived: document.getElementById('chunks-received'),
            audioElements: document.getElementById('audio-elements'),
            simultaneousPlay: document.getElementById('simultaneous-play'),
            firstAudioLatency: document.getElementById('first-audio-latency')
        };
    }
    
    async getSessionId() {
        try {
            const response = await fetch('/api/get-session-id');
            const data = await response.json();
            this.sessionId = data.session_id;
            this.log(`✅ Session ID obtained: ${this.sessionId}`, 'success');
        } catch (error) {
            this.log(`❌ Failed to get session ID: ${error.message}`, 'error');
            throw error;
        }
    }
    
    async startDiagnosticTest() {
        if (this.isRunning) {
            this.log('⚠️ Diagnostic test already running', 'warning');
            return;
        }
        
        const settings = this.getCurrentSettings();
        if (!settings.text) {
            this.log('⚠️ Please enter text to test', 'warning');
            return;
        }
        
        try {
            this.log('🔍 Starting diagnostic test...', 'diagnostic');
            this.log(`📝 Test text: "${settings.text}"`, 'diagnostic');
            this.log(`🎵 Voice: ${settings.voice_id}, Model: ${settings.model_id}, Profile: ${settings.quality_profile}`, 'diagnostic');
            
            // Reset metrics
            this.resetMetrics();
            this.isRunning = true;
            this.startTime = Date.now();
            
            // Create WebSocket connection with monitoring
            await this.createMonitoredWebSocket();
            
            // Send TTS request
            await this.sendTTSRequest(settings);
            
            // Enable stop button
            const testBtn = document.getElementById('diagnostic-test-btn');
            if (testBtn) {
                testBtn.disabled = true;
                testBtn.textContent = '🔄 Running Diagnostic...';
            }
            
        } catch (error) {
            this.log(`❌ Diagnostic test failed: ${error.message}`, 'error');
            this.isRunning = false;
            this.enableTestButton();
        }
    }
    
    async createMonitoredWebSocket() {
        const connectionId = `conn_${this.connectionCounter++}`;
        const wsUrl = `ws://${window.location.host}/ws/audio/${encodeURIComponent(this.sessionId)}`;
        
        this.log(`🔌 Creating WebSocket connection: ${connectionId}`, 'diagnostic');
        this.log(`📡 WebSocket URL: ${wsUrl}`, 'diagnostic');
        
        // Check for duplicate connections
        const existingActive = Array.from(this.connections.values()).filter(conn => conn.state === 'active').length;
        if (existingActive > 0) {
            this.duplicateConnections++;
            this.log(`⚠️ DUPLICATE CONNECTION DETECTED! Already have ${existingActive} active connections`, 'warning');
            this.updateStatus('duplicate-connections', this.duplicateConnections);
            this.addConnectionToList(connectionId, 'DUPLICATE', 'duplicate');
        }
        
        const websocket = new WebSocket(wsUrl);
        const connectionInfo = {
            id: connectionId,
            websocket: websocket,
            state: 'connecting',
            created: Date.now(),
            url: wsUrl,
            messages: 0,
            chunks: 0
        };
        
        this.connections.set(connectionId, connectionInfo);
        this.updateConnectionMetrics();
        this.addConnectionToList(connectionId, 'Connecting...', 'active');
        
        // Monitor WebSocket events
        websocket.onopen = () => {
            connectionInfo.state = 'active';
            connectionInfo.connected = Date.now();
            this.activeConnections++;
            
            this.log(`✅ WebSocket connected: ${connectionId}`, 'success');
            this.updateConnectionMetrics();
            this.updateConnectionInList(connectionId, 'Active', 'active');
        };
        
        websocket.onclose = (event) => {
            connectionInfo.state = 'closed';
            connectionInfo.closed = Date.now();
            connectionInfo.closeCode = event.code;
            connectionInfo.closeReason = event.reason;
            this.activeConnections = Math.max(0, this.activeConnections - 1);
            
            this.log(`📡 WebSocket closed: ${connectionId} (code: ${event.code}, reason: ${event.reason})`, 'info');
            this.updateConnectionMetrics();
            this.updateConnectionInList(connectionId, `Closed (${event.code})`, 'closed');
        };
        
        websocket.onerror = (error) => {
            this.log(`❌ WebSocket error: ${connectionId} - ${error}`, 'error');
        };
        
        websocket.onmessage = (event) => {
            connectionInfo.messages++;
            this.handleDiagnosticMessage(event, connectionId);
        };
        
        // Store reference
        this.currentWebSocket = websocket;
        this.currentConnectionId = connectionId;
        
        // Wait for connection
        await new Promise((resolve, reject) => {
            websocket.onopen = resolve;
            websocket.onerror = reject;
            setTimeout(() => reject(new Error('WebSocket connection timeout')), 5000);
        });
    }
    
    handleDiagnosticMessage(event, connectionId) {
        const connectionInfo = this.connections.get(connectionId);
        
        if (event.data instanceof Blob) {
            // Binary audio chunk
            connectionInfo.chunks++;
            this.chunksReceived++;
            
            const chunkInfo = {
                type: 'chunk',
                connectionId: connectionId,
                size: event.data.size,
                timestamp: Date.now(),
                sequence: this.chunksReceived
            };
            
            this.log(`📦 Audio chunk received: ${connectionId} (size: ${event.data.size} bytes, seq: ${this.chunksReceived})`, 'diagnostic');
            
            // Record first audio timing
            if (this.chunksReceived === 1 && this.startTime) {
                this.firstAudioTime = Date.now();
                const latency = this.firstAudioTime - this.startTime;
                this.updateStatus('first-audio-latency', `${latency}ms`);
                this.log(`🚀 First audio chunk in ${latency}ms`, latency < 500 ? 'success' : 'warning');
            }
            
            this.chunkTimeline.push(chunkInfo);
            this.addToChunkTimeline('received', `Chunk ${this.chunksReceived} (${event.data.size}b) from ${connectionId}`);
            this.updateStatus('chunks-received', this.chunksReceived);
            
            // Simulate audio playback for monitoring (no actual sequencing)
            this.simulateAudioPlayback(event.data, this.chunksReceived, connectionId);
            
        } else {
            // Text message (status update)
            try {
                const message = JSON.parse(event.data);
                this.log(`📨 Status message from ${connectionId}: ${message.type} - ${message.text || 'no text'}`, 'info');
                
                if (message.type === 'audio_streaming_complete') {
                    this.log(`🏁 Streaming complete from ${connectionId}`, 'success');
                    this.onTestComplete();
                }
            } catch (e) {
                this.log(`📨 Non-JSON message from ${connectionId}: ${event.data}`, 'info');
            }
        }
    }
    
    async simulateAudioPlayback(audioBlob, sequence, connectionId) {
        // Create audio element for monitoring (mirrors original behavior)
        const elementId = `audio_${this.audioElementCounter++}`;
        const audio = document.createElement('audio');
        
        const elementInfo = {
            id: elementId,
            element: audio,
            created: Date.now(),
            sequence: sequence,
            connectionId: connectionId,
            size: audioBlob.size,
            state: 'created'
        };
        
        this.audioElements.set(elementId, elementInfo);
        this.updateStatus('audio-elements', this.audioElements.size);
        
        // Monitor for simultaneous playback
        const currentlyPlaying = Array.from(this.audioElements.values()).filter(el => el.state === 'playing').length;
        if (currentlyPlaying > 0) {
            this.simultaneousPlayCount++;
            this.log(`⚠️ SIMULTANEOUS PLAYBACK DETECTED! ${currentlyPlaying + 1} audio elements playing`, 'warning');
            this.updateStatus('simultaneous-play', this.simultaneousPlayCount);
            this.addToChunkTimeline('duplicate', `OVERLAP: ${elementId} while ${currentlyPlaying} others playing`);
        }
        
        // Set up audio element
        const audioUrl = URL.createObjectURL(audioBlob);
        audio.src = audioUrl;
        audio.style.display = 'none';
        document.body.appendChild(audio);
        
        // Monitor playback events
        audio.addEventListener('play', () => {
            elementInfo.state = 'playing';
            elementInfo.playStarted = Date.now();
            this.log(`▶️ Audio playback started: ${elementId} (seq: ${sequence})`, 'diagnostic');
            this.addToChunkTimeline('played', `Playing ${elementId} (seq: ${sequence}) from ${connectionId}`);
            
            // Check for overlaps
            const nowPlaying = Array.from(this.audioElements.values()).filter(el => el.state === 'playing').length;
            if (nowPlaying > 1) {
                this.log(`🔄 OVERLAP: ${nowPlaying} audio elements now playing simultaneously`, 'warning');
            }
        });
        
        audio.addEventListener('ended', () => {
            elementInfo.state = 'ended';
            elementInfo.playEnded = Date.now();
            elementInfo.duration = elementInfo.playEnded - elementInfo.playStarted;
            this.log(`⏹️ Audio playback ended: ${elementId} (duration: ${elementInfo.duration}ms)`, 'diagnostic');
            
            // Cleanup
            URL.revokeObjectURL(audioUrl);
            document.body.removeChild(audio);
        });
        
        audio.addEventListener('error', (e) => {
            elementInfo.state = 'error';
            this.log(`❌ Audio playback error: ${elementId} - ${e.target.error?.message || 'Unknown error'}`, 'error');
        });
        
        // Attempt to play (mirrors original behavior)
        try {
            const playPromise = audio.play();
            if (playPromise !== undefined) {
                await playPromise;
            }
        } catch (error) {
            elementInfo.state = 'failed';
            if (error.name === 'NotAllowedError') {
                this.log(`🔒 Autoplay prevented: ${elementId}`, 'warning');
            } else {
                this.log(`❌ Audio play failed: ${elementId} - ${error.message}`, 'error');
            }
        }
    }
    
    async sendTTSRequest(settings) {
        try {
            this.log('📡 Sending TTS request to ElevenLabs endpoint...', 'diagnostic');
            
            const requestBody = {
                session_id: this.sessionId,
                text: settings.text,
                voice_id: settings.voice_id,
                model_id: settings.model_id,
                quality_profile: settings.quality_profile
            };
            
            this.log(`📤 Request body: ${JSON.stringify(requestBody, null, 2)}`, 'diagnostic');
            
            const response = await fetch('/api/get-speech-elevenlabs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com'
                },
                body: JSON.stringify(requestBody)
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const responseData = await response.json();
            this.log(`📥 TTS request successful: ${JSON.stringify(responseData)}`, 'success');
            this.log('⏳ Waiting for audio chunks via WebSocket...', 'diagnostic');
            
        } catch (error) {
            throw new Error(`TTS request failed: ${error.message}`);
        }
    }
    
    onTestComplete() {
        this.isRunning = false;
        const totalTime = Date.now() - this.startTime;
        
        this.log(`🏁 Diagnostic test complete - Total time: ${(totalTime / 1000).toFixed(1)}s`, 'success');
        this.log('📊 Final Analysis:', 'diagnostic');
        this.log(`   - Total connections created: ${this.connectionCounter}`, 'diagnostic');
        this.log(`   - Active connections: ${this.activeConnections}`, 'diagnostic');
        this.log(`   - Duplicate connections: ${this.duplicateConnections}`, 'diagnostic');
        this.log(`   - Chunks received: ${this.chunksReceived}`, 'diagnostic');
        this.log(`   - Audio elements created: ${this.audioElements.size}`, 'diagnostic');
        this.log(`   - Simultaneous playback events: ${this.simultaneousPlayCount}`, 'diagnostic');
        
        // Analysis
        if (this.duplicateConnections > 0) {
            this.log('🔴 ROOT CAUSE DETECTED: Multiple WebSocket connections to same session', 'error');
        }
        
        if (this.simultaneousPlayCount > 0) {
            this.log('🟠 ISSUE DETECTED: Simultaneous audio playback (likely cause of duplication)', 'warning');
        }
        
        if (this.duplicateConnections === 0 && this.simultaneousPlayCount === 0) {
            this.log('🟢 No obvious connection or timing issues detected', 'success');
        }
        
        this.enableTestButton();
    }
    
    stopDiagnosticTest() {
        this.log('⏹️ Stopping diagnostic test...', 'diagnostic');
        this.isRunning = false;
        
        // Close WebSocket connections
        this.connections.forEach((connectionInfo, connectionId) => {
            if (connectionInfo.websocket && connectionInfo.websocket.readyState === WebSocket.OPEN) {
                this.log(`🔌 Closing WebSocket: ${connectionId}`, 'diagnostic');
                connectionInfo.websocket.close();
            }
        });
        
        // Stop audio elements
        this.audioElements.forEach((elementInfo, elementId) => {
            if (elementInfo.element && !elementInfo.element.paused) {
                this.log(`⏸️ Stopping audio element: ${elementId}`, 'diagnostic');
                elementInfo.element.pause();
            }
        });
        
        this.enableTestButton();
    }
    
    resetMetrics() {
        this.connections.clear();
        this.audioElements.clear();
        this.chunkTimeline = [];
        this.connectionCounter = 0;
        this.audioElementCounter = 0;
        this.activeConnections = 0;
        this.duplicateConnections = 0;
        this.chunksReceived = 0;
        this.simultaneousPlayCount = 0;
        this.startTime = null;
        this.firstAudioTime = null;
        
        // Reset UI
        this.updateConnectionMetrics();
        this.updateStatus('chunks-received', 0);
        this.updateStatus('audio-elements', 0);
        this.updateStatus('simultaneous-play', 0);
        this.updateStatus('first-audio-latency', '-');
        
        // Clear lists
        document.getElementById('connection-list').innerHTML = '<div style="color: #888; font-style: italic;">No connections yet...</div>';
        document.getElementById('chunk-timeline').innerHTML = '<div style="color: #888; font-style: italic;">No audio activity yet...</div>';
    }
    
    updateConnectionMetrics() {
        this.updateStatus('active-connections', this.activeConnections);
        this.updateStatus('total-connections', this.connectionCounter);
        this.updateStatus('duplicate-connections', this.duplicateConnections);
    }
    
    addConnectionToList(connectionId, status, cssClass) {
        const list = document.getElementById('connection-list');
        const item = document.createElement('div');
        item.className = `connection-item ${cssClass}`;
        item.id = `conn-${connectionId}`;
        item.innerHTML = `
            <span>${connectionId}</span>
            <span>${status}</span>
        `;
        list.appendChild(item);
        list.scrollTop = list.scrollHeight;
    }
    
    updateConnectionInList(connectionId, status, cssClass) {
        const item = document.getElementById(`conn-${connectionId}`);
        if (item) {
            item.className = `connection-item ${cssClass}`;
            item.querySelector('span:last-child').textContent = status;
        }
    }
    
    addToChunkTimeline(type, message) {
        const timeline = document.getElementById('chunk-timeline');
        const entry = document.createElement('div');
        entry.className = `chunk-entry ${type}`;
        entry.innerHTML = `
            <span>${new Date().toLocaleTimeString()}</span>
            <span>${message}</span>
        `;
        timeline.appendChild(entry);
        timeline.scrollTop = timeline.scrollHeight;
    }
    
    enableTestButton() {
        const testBtn = document.getElementById('diagnostic-test-btn');
        if (testBtn) {
            testBtn.disabled = false;
            testBtn.textContent = '🔍 Start Diagnostic Test';
        }
    }
    
    getCurrentSettings() {
        return {
            text: document.getElementById('test-text')?.value.trim() || '',
            voice_id: document.getElementById('voice-select')?.value || '21m00Tcm4TlvDq8ikWAM',
            model_id: document.getElementById('model-select')?.value || 'eleven_flash_v2_5',
            quality_profile: document.getElementById('profile-select')?.value || 'balanced'
        };
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
        
        // Also log to browser console
        console.log(`[WebSocketDiagnostic] ${message}`);
    }
    
    clearLogs() {
        if (this.logElement) {
            this.logElement.innerHTML = '';
            this.log('📝 Diagnostic console cleared', 'diagnostic');
            this.log('🔍 Ready for new diagnostic tests', 'info');
        }
    }
}

// Global diagnostic tool instance
let diagnosticTool = null;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
    try {
        diagnosticTool = new WebSocketDiagnosticTool();
        console.log('✅ WebSocket Diagnostic Tool initialized successfully');
    } catch (error) {
        console.error('❌ Failed to initialize WebSocket Diagnostic Tool:', error);
    }
});

// Global functions for UI
async function startDiagnosticTest() {
    if (diagnosticTool) {
        await diagnosticTool.startDiagnosticTest();
    }
}

function stopDiagnosticTest() {
    if (diagnosticTool) {
        diagnosticTool.stopDiagnosticTest();
    }
}

function clearDiagnosticLogs() {
    if (diagnosticTool) {
        diagnosticTool.clearLogs();
    }
}