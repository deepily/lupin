/**
 * Queue Management JavaScript
 * Handles job queue visualization, audio playback, and Socket.IO communication
 */

var audioContext = null;
var hybridTTS = null; // HybridTTS instance for job completion audio
var jobCache = null; // JobCompletionCache instance for advanced caching
var notificationSounds = {}; // Cached notification sound objects

function createAudioContext() {
    // Check if the AudioContext is already created
    if ( window.AudioContext || window.webkitAudioContext ) {
        audioContext = new ( window.AudioContext || window.webkitAudioContext )();
        console.log( "AudioContext created!" );
    } else {
        console.log( "AudioContext is not supported in this browser" );
    }
}

// Initialize HybridTTS for job completion audio
async function initializeHybridTTS() {
    try {
        // Wait for sessionId if not available yet
        if (!sessionId) {
            console.log('Waiting for queue WebSocket to establish session ID...');
            // Wait up to 5 seconds for sessionId
            let attempts = 0;
            while (!sessionId && attempts < 50) {
                await new Promise(resolve => setTimeout(resolve, 100));
                attempts++;
            }
        }
        
        hybridTTS = new HybridTTS({
            sessionId: sessionId, // Pass the session ID to HybridTTS
            wsUrl: sessionId ? `ws://${window.location.host}/ws/${sessionId}` : undefined,
            cacheEnabled: true,
            cacheMaxSize: 50 * 1024 * 1024, // 50MB cache for job audio
            cacheMaxAge: 7 * 24 * 60 * 60 * 1000, // 7 days
            onStatusUpdate: (message, type) => {
                console.log(`HybridTTS Status: ${message} (${type})`);
            },
            onProgressUpdate: (message) => {
                console.log(`HybridTTS Progress: ${message}`);
            },
            onComplete: (audioUrl, totalTime) => {
                console.log(`HybridTTS Complete in ${totalTime}s`);
            },
            onError: (error) => {
                console.error('HybridTTS Error:', error);
            }
        });
        
        await hybridTTS.initialize();
        console.log('HybridTTS initialized successfully for job audio');
    } catch (error) {
        console.error('Failed to initialize HybridTTS:', error);
        // Fall back to simple audio playback if HybridTTS fails
        hybridTTS = null;
    }
}

// Initialize JobCompletionCache for advanced message caching
async function initializeJobCache() {
    try {
        jobCache = new JobCompletionCache({
            cacheEnabled: true,
            cacheMaxSize: 10 * 1024 * 1024, // 10MB cache for text messages
            cacheMaxAge: 30 * 24 * 60 * 60 * 1000, // 30 days
            maxEntries: 1000 // Maximum number of job messages
        });
        
        console.log('JobCompletionCache initialized successfully');
    } catch (error) {
        console.error('Failed to initialize JobCompletionCache:', error);
        // Fall back to simple Map storage if cache fails
        jobCache = null;
    }
}

// Initialize notification sounds for instant playback
function initializeNotificationSounds() {
    try {
        // Pre-load and cache notification sounds for instant playback
        notificationSounds = {
            lowPriority: new Audio('/static/audio/notification-low-priority.mp3'),
            highPriority: new Audio('/static/audio/notification-high-priority.mp3'),
            error: new Audio('/static/audio/notification-error.mp3')
        };
        
        // Set properties for better performance
        Object.values(notificationSounds).forEach(audio => {
            audio.preload = 'auto';
            audio.volume = 0.7; // Slightly quieter than default
        });
        
        console.log('Notification sounds initialized and cached');
    } catch (error) {
        console.error('Failed to initialize notification sounds:', error);
        notificationSounds = {};
    }
}

// Play notification sound based on priority
async function playNotificationSoundByPriority( priority ) {
    try {
        let audio = null;
        
        // Map priority to appropriate sound
        switch ( priority ) {
            case "urgent":
            case "high":
                audio = notificationSounds.highPriority;
                console.log( `Playing high priority notification sound for ${priority} priority` );
                break;
            case "medium":
            case "low":
                audio = notificationSounds.lowPriority;
                console.log( `Playing low priority notification sound for ${priority} priority` );
                break;
            case "error":
                audio = notificationSounds.error;
                console.log( `Playing error notification sound` );
                break;
            default:
                // Default to low priority sound for unknown priorities
                audio = notificationSounds.lowPriority;
                console.log( `Playing default (low priority) notification sound for unknown priority: ${priority}` );
                break;
        }
        
        if ( audio ) {
            // Reset audio to beginning in case it was played before
            audio.currentTime = 0;
            await audio.play();
        } else {
            console.warn( 'No notification sound available for priority:', priority );
        }
        
    } catch ( error ) {
        console.error( 'Failed to play notification sound:', error );
        // Continue execution even if sound fails
    }
}

// Call createAudioContext() when the webpage is loaded and DOM is available
document.addEventListener( "DOMContentLoaded", async function() {
    console.log( "DOM fully loaded and parsed" );
    
    // Initialize notification sounds
    initializeNotificationSounds();
    
    // Update auth status initially
    updateAuthStatus();
    
    // Add event listeners for user email changes
    const userEmailInput = document.getElementById( "user-email-input" );
    if ( userEmailInput ) {
        userEmailInput.addEventListener( "input", updateAuthStatus );
        userEmailInput.addEventListener( "change", function() {
            // Reconnect WebSocket with new user credentials
            if ( queueSocket ) {
                queueSocket.close();
            }
            setTimeout( connectToQueueWebSocket, 500 );
            
            // Refresh all queues with new authentication
            setTimeout( function() {
                updateQueueLists( "todo" );
                updateQueueLists( "run" );
                updateQueueLists( "done" );
                updateQueueLists( "dead" );
            }, 1000 );
        });
    }
    
    setEnterKeyListener();
    createAudioContext();
    
    // Initialize HybridTTS for job completion audio
    await initializeHybridTTS();
    
    // Initialize JobCompletionCache for advanced message caching
    await initializeJobCache();
    
    // Connect to FastAPI WebSocket first to get session ID
    await connectToQueueWebSocket();
    
    updateQueueLists( "todo" );
    updateQueueLists( "run" );
    updateQueueLists( "done" );
    updateQueueLists( "dead" );
    addClickEventToDoneList();
} );

function addClickEventToDoneList() {
    console.log( "Adding click event to '#done-list'..." );

    const listItems = document.querySelectorAll("#done-list li");

    listItems.forEach( item => {
        console.log( "Adding click event to item:", item );

        const playAudioSpan      = item.querySelector( ".play" );
        const deleteSnapshotSpan = item.querySelector( ".delete" );

        if ( playAudioSpan ) {
            playAudioSpan.onclick = function() {
                console.log( "Playing audio:", item.id );
                playAnswer( item.id );
            };
        }

        if ( deleteSnapshotSpan ) {
            deleteSnapshotSpan.textContent = "🗑";
            deleteSnapshotSpan.onclick = function() {
                const confirmDelete = confirm( "Are you sure you want to delete?" );
                if ( confirmDelete ) {
                    console.log( "Deleting snapshot:", item.id );
                    deleteSnapshot( item.id );
                } else {
                    console.log( "Not deleting snapshot:", item.id );
                }
            };
        }
    } );
}

// Submit a question with authentication
function submitQuestion() {
    const questionInput = document.getElementById( "question-input" );
    const question = questionInput.value.trim();
    const userEmail = getCurrentUserEmail();
    
    if ( !question ) {
        alert( "Please enter a question" );
        return;
    }
    
    if ( !userEmail ) {
        alert( "Please enter a user email" );
        return;
    }
    
    if ( !sessionId ) {
        alert( "Session not established. Please wait for connection." );
        return;
    }
    
    // Use the existing WebSocket session ID
    const websocketId = sessionId;
    console.log( `Using session ID as websocket ID: ${websocketId}` );
    
    // Show loading status
    const statusElement = document.getElementById( "response-status" );
    statusElement.textContent = "Submitting...";
    statusElement.style.color = "#007bff";
    
    const url = `/api/push?question=${encodeURIComponent(question)}&websocket_id=${websocketId}`;
    
    fetch( url, {
        headers: {
            'Authorization': getAuthHeader(),
            'X-Session-ID': sessionId
        }
    })
    .then( response => {
        if ( !response.ok ) {
            throw new Error( `HTTP error! status: ${response.status}` );
        }
        return response.json();
    })
    .then( data => {
        console.log( "Question submitted successfully:", data );
        statusElement.textContent = "✓ Submitted";
        statusElement.style.color = "#28a745";
        
        // Clear the input
        questionInput.value = "";
        
        // Refresh the todo queue to show the new job
        setTimeout( () => updateQueueLists( "todo" ), 500 );
    })
    .catch( error => {
        console.error( "Error submitting question:", error );
        statusElement.textContent = "✗ Error";
        statusElement.style.color = "#dc3545";
    });
}

// Delete a real COSA job snapshot (called from 🗑️ button in done queue)
// IMPORTANT: This removes the job permanently from the done queue history.
function deleteSnapshot( id ) {
    const confirmDelete = confirm( "Are you sure you want to permanently delete this job from your history? This action cannot be undone." );
    if ( !confirmDelete ) {
        return; // User cancelled deletion
    }
    
    fetch( "/api/delete-snapshot/" + id, {
        headers: {
            'Authorization': getAuthHeader()
        }
    })
        .then( response => {
            if ( response.status !== 200 ) {
                throw new Error( `HTTP error, status = ${ response.status }` );
            }
            return response.text();
        } ) .then( ( text ) => {
            console.log( "Snapshot deletion response:", text );
            // Refresh the done queue to reflect the deletion
            updateQueueLists( "done" );
        } )
        .catch( error => console.error( "Error deleting snapshot:", error ) );
}

function playAnswer( id ) {
    url = "/get-answer/" + id;
    console.log( url );
    let audio = new Audio( url );
    audio.play();
}

// FastAPI WebSocket connection for queue events
var queueSocket = null;
var sessionId = null;


async function connectToQueueWebSocket() {
    try {
        // Update debug status
        updateWebSocketDebugInfo( "Connecting...", "Connecting", "None" );
        
        // Get session ID first
        const response = await fetch( "/api/get-session-id" );
        const data = await response.json();
        sessionId = data.session_id;
        console.log( "Got session ID:", sessionId );
        
        // Update debug info with session ID
        const authToken = getAuthHeader().replace( "Bearer ", "" );
        updateWebSocketDebugInfo( sessionId, "Connecting", authToken );
        
        // Connect to queue WebSocket
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws/queue/${sessionId}`;
        console.log( "Connecting to queue WebSocket:", wsUrl );
        
        queueSocket = new WebSocket( wsUrl );
        
        queueSocket.onopen = function() {
            console.log( "Connected to FastAPI queue WebSocket" );
            
            // Send authentication with current user ID
            const authToken = getAuthHeader().replace( "Bearer ", "" );
            updateWebSocketDebugInfo( sessionId, "Connected", authToken );
            console.log( "Sending auth message with token:", authToken );
            queueSocket.send( JSON.stringify({
                "type": "auth",
                "token": authToken,
                "session_id": sessionId
            }));
        };
        
        queueSocket.onmessage = function( event ) {
            const data = JSON.parse( event.data );
            console.log( "Received queue event:", data );
            
            switch( data.type ) {
                case "connect":
                    console.log( "Queue WebSocket connection confirmed:", data.message );
                    break;
                    
                case "auth_success":
                    console.log( "WebSocket authentication successful for user:", data.user_id );
                    const successToken = getAuthHeader().replace( "Bearer ", "" );
                    updateWebSocketDebugInfo( sessionId, "Authenticated ✓", successToken );
                    const statusElement = document.getElementById( "auth-status" );
                    if ( statusElement ) {
                        statusElement.textContent = `✓ WebSocket authenticated: ${data.user_id}`;
                        statusElement.style.color = "#28a745";
                    }
                    
                    // Store the server-provided user ID for notifications
                    if ( notificationState ) {
                        notificationState.userId = data.user_id;
                        console.log( `Notification state updated with server user ID: ${data.user_id}` );
                        
                        // Load initial notifications now that we have the correct user ID
                        loadInitialNotifications();
                    }
                    break;
                    
                case "auth_error":
                    console.error( "WebSocket authentication failed:", data.message );
                    const errorToken = getAuthHeader().replace( "Bearer ", "" );
                    updateWebSocketDebugInfo( sessionId, "Auth Failed ✗", errorToken );
                    const errorElement = document.getElementById( "auth-status" );
                    if ( errorElement ) {
                        errorElement.textContent = `✗ WebSocket auth failed: ${data.message}`;
                        errorElement.style.color = "#dc3545";
                    }
                    break;
                    
                case "time_update":
                    document.getElementById( "clock" ).innerHTML = data.date;
                    break;
                    
                case "todo_update":
                    document.getElementById( "todo" ).innerHTML = "Jobs TODO: " + data.value;
                    updateQueueLists( "todo" );
                    break;
                    
                case "run_update":
                    document.getElementById( "run" ).innerHTML = "Jobs RUNNING: " + data.value;
                    updateQueueLists( "run" );
                    break;
                    
                case "done_update":
                    document.getElementById( "done" ).innerHTML = "Jobs DONE: " + data.value;
                    updateQueueLists( "done" );
                    break;
                    
                case "dead_update":
                    document.getElementById( "dead" ).innerHTML = "Jobs DEAD: " + data.value;
                    updateQueueLists( "dead" );
                    break;
                    
                case "notification_sound_update":
                    handleNotificationSound( data );
                    break;
                    
                case "audio_update":
                    handleAudioUpdate( data );
                    break;
                    
                case "user_notification":
                    handleUserNotification( data );
                    break;
                    
                case "task":
                case "progress": 
                case "alert":
                case "custom":
                    // Legacy Claude Code notification types - now handled via notification_update
                    console.log( "Received legacy notification event (now handled via notification_update):", data.type );
                    break;
                    
                case "notification_update":
                    // Handle real-time notification updates from NotificationFifoQueue
                    handleNotificationUpdate( data );
                    break;
                    
                default:
                    console.log( "Unknown queue event type:", data.type );
            }
        };
        
        queueSocket.onerror = function( error ) {
            console.error( "Queue WebSocket error:", error );
        };
        
        queueSocket.onclose = function() {
            console.log( "Queue WebSocket connection closed" );
            updateWebSocketDebugInfo( sessionId || "Unknown", "Disconnected", "None" );
            // Attempt to reconnect after 5 seconds
            setTimeout( connectToQueueWebSocket, 5000 );
        };
        
    } catch( error ) {
        console.error( "Failed to connect to queue WebSocket:", error );
        // Retry connection after 5 seconds
        setTimeout( connectToQueueWebSocket, 5000 );
    }
}

function updateQueueLists( queue_name ) {
    console.log( `>>> updateQueueLists called for: ${queue_name}` );
    const url = "/api/get-queue/" + queue_name;
    console.log( `>>> Fetching URL: ${url}` );
    
    fetch( url, {
        headers: {
            'Authorization': getAuthHeader()
        }
    })
        .then( response => {
            console.log( `>>> Response status for ${queue_name}:`, response.status );
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then( data => {
            console.log( `>>> Data received for ${queue_name}:`, data );
            if ( queue_name === "todo" ) {
                document.getElementById( "todo-list" ).innerHTML = data.todo_jobs.join( "" );
            } else if ( queue_name === "run" ) {
                document.getElementById( "run-list" ).innerHTML = data.run_jobs.join( "" );
            } else if ( queue_name === "done" ) {
                document.getElementById( "done-list" ).innerHTML = data.done_jobs.join( "" );
                addClickEventToDoneList();
            } else if ( queue_name === "dead" ) {
                document.getElementById( "dead-list" ).innerHTML = data.dead_jobs.join( "" );
            } else {
                console.log( "Unknown queue name:", queue_name );
            }
        } )
        .catch( error => console.error( "Error:", error ) );
}

// Unified Audio Queue System - Event-Driven Architecture
const unifiedAudioQueue = {
    items: [],        // Array of {type: 'tts'|'audio', content: string|url, priority: string, id: number}
    isPlaying: false, // Simple state based on events
    currentAudio: null,
    currentItem: null
};

// Legacy variables kept for compatibility (will be removed later)
var audioQueue   = []; // Old audio queue - to be migrated
var playing      = false; // Old playing state - to be migrated
var quiet        = false;
var lastAudioURL = null;

// Add item to unified audio queue
function addToAudioQueue( type, content, priority = "medium" ) {
    const item = {
        type,      // 'tts' or 'audio'
        content,   // text for TTS, URL for audio
        priority,
        id: Date.now(),
        timestamp: new Date().toISOString()
    };
    
    console.log( `Adding to audio queue (${type}, priority: ${priority}): "${content.substring ? content.substring(0, 50) + '...' : content}"` );
    
    unifiedAudioQueue.items.push( item );
    
    // Sort by priority if needed
    if ( priority === "urgent" || priority === "high" ) {
        const priorityOrder = { urgent: 0, high: 1, medium: 2, low: 3 };
        unifiedAudioQueue.items.sort( ( a, b ) => priorityOrder[a.priority] - priorityOrder[b.priority] );
    }
    
    console.log( `Audio queue now has ${unifiedAudioQueue.items.length} items` );
    updateQueueDisplay();
    
    // Auto-start playback if nothing is playing
    if ( !unifiedAudioQueue.isPlaying ) {
        console.log( "Queue was idle, starting playback automatically" );
        playNext();
    } else {
        console.log( "Already playing, item will play when its turn comes" );
    }
}

// Wrapper function for TTS compatibility
function addToTTSQueue( message, priority = "medium", autoPlay = true ) {
    addToAudioQueue( 'tts', message, priority );
}

// Legacy wrapper for backward compatibility
async function queueTTSMessage( message, priority = "medium", autoPlay = true ) {
    addToAudioQueue( 'tts', message, priority );
}

// Event-driven playback - plays next item in queue
async function playNext() {
    if ( unifiedAudioQueue.items.length === 0 ) {
        console.log( "Queue empty, playback complete" );
        unifiedAudioQueue.isPlaying = false;
        unifiedAudioQueue.currentItem = null;
        updateQueueDisplay();
        return;
    }
    
    unifiedAudioQueue.isPlaying = true;
    const item = unifiedAudioQueue.items.shift();
    unifiedAudioQueue.currentItem = item;
    
    console.log( `Playing ${item.type} (${item.priority}): "${item.content.substring ? item.content.substring(0, 50) + '...' : item.content}"` );
    
    try {
        if ( item.type === 'tts' && hybridTTS ) {
            console.log( 'Attempting HybridTTS speak...' );
            
            try {
                // Create a promise to handle TTS completion
                const ttsPromise = hybridTTS.speak( item.content );
                console.log( 'HybridTTS promise created:', ttsPromise );
                
                // HybridTTS returns the audio element in its onComplete callback
                // We need to wait for it to complete before moving to next
                const result = await ttsPromise;
                console.log( `TTS completed: "${item.content.substring(0, 50)}..."` );
                
                // Small pause between items for clarity
                if ( unifiedAudioQueue.items.length > 0 ) {
                    await new Promise( resolve => setTimeout( resolve, 300 ) );
                }
                
                // Continue to next item
                playNext();
            } catch ( ttsError ) {
                console.error( 'HybridTTS speak failed:', ttsError );
                
                // Reset HybridTTS if needed
                if ( hybridTTS.audioElement && hybridTTS.audioElement.src === '' ) {
                    console.log( 'HybridTTS has empty audio src, resetting...' );
                    hybridTTS.isRequesting = false;
                }
                
                // Throw to outer catch block to play fallback
                throw ttsError;
            }
            
        } else if ( item.type === 'audio' ) {
            // Regular audio playback
            const audio = new Audio( item.content );
            setupAudioEvents( audio );
            unifiedAudioQueue.currentAudio = audio;
            await audio.play();
            
        } else {
            // Fallback for unsupported types or missing TTS
            console.log( `Unsupported type or missing handler for ${item.type}, playing fallback sound` );
            fallbackToNotificationSound();
            // Small delay for fallback sound
            await new Promise( resolve => setTimeout( resolve, 1000 ) );
            playNext();
        }
    } catch ( error ) {
        console.error( `Playback failed for ${item.type}:`, error );
        
        // If HybridTTS is stuck, reset it
        if ( item.type === 'tts' && hybridTTS && error.message === 'Request already in progress' ) {
            console.log( 'Resetting HybridTTS stuck state...' );
            if ( hybridTTS.isRequesting ) {
                hybridTTS.isRequesting = false;
            }
            if ( hybridTTS.currentRequest ) {
                hybridTTS.currentRequest = null;
            }
        }
        
        // If TTS failed, play fallback sound
        if ( item.type === 'tts' ) {
            console.log( 'TTS failed, playing fallback notification sound' );
            const fallbackUrl = '/static/audio/gentle-gong.mp3';
            const audio = new Audio( fallbackUrl );
            setupAudioEvents( audio );
            unifiedAudioQueue.currentAudio = audio;
            
            try {
                await audio.play();
                return; // Let the audio events handle moving to next item
            } catch ( fallbackError ) {
                console.error( 'Fallback audio also failed:', fallbackError );
            }
        }
        
        // On error, automatically continue to next item
        unifiedAudioQueue.currentAudio = null;
        playNext();
    }
}

// Set up event handlers for audio elements
function setupAudioEvents( audio ) {
    // When audio ends, play next item
    audio.addEventListener( 'ended', () => {
        console.log( "Audio ended, playing next item" );
        unifiedAudioQueue.currentAudio = null;
        unifiedAudioQueue.currentItem = null;
        playNext();
    });
    
    // On error, skip to next
    audio.addEventListener( 'error', ( e ) => {
        console.error( 'Audio playback error:', e );
        
        // Play error notification sound for audio failures
        playNotificationSoundByPriority( "error" );
        
        unifiedAudioQueue.currentAudio = null;
        unifiedAudioQueue.currentItem = null;
        playNext();
    });
    
    // Update UI on state changes
    audio.addEventListener( 'play', () => updateQueueDisplay() );
    audio.addEventListener( 'pause', () => updateQueueDisplay() );
}

// Legacy wrapper for backward compatibility
async function processTTSQueue() {
    // This now just triggers the unified queue
    if ( unifiedAudioQueue.items.some( item => item.type === 'tts' ) ) {
        playQueue();
    }
}

// Manual queue controls
function playQueue() {
    if ( !unifiedAudioQueue.isPlaying && unifiedAudioQueue.items.length > 0 ) {
        console.log( "Manually starting queue playback" );
        playNext();
    } else if ( unifiedAudioQueue.isPlaying ) {
        console.log( "Queue is already playing" );
    } else {
        console.log( "Queue is empty" );
    }
}

// Legacy wrapper
async function startTTSQueue() {
    playQueue();
}

function pauseQueue() {
    if ( unifiedAudioQueue.currentAudio ) {
        unifiedAudioQueue.currentAudio.pause();
        console.log( "Queue paused" );
    }
}

function clearQueue() {
    unifiedAudioQueue.items = [];
    if ( unifiedAudioQueue.currentAudio ) {
        unifiedAudioQueue.currentAudio.pause();
        unifiedAudioQueue.currentAudio = null;
    }
    unifiedAudioQueue.isPlaying = false;
    unifiedAudioQueue.currentItem = null;
    console.log( "Queue cleared" );
    updateQueueDisplay();
}

// Get queue status for debugging
function getQueueStatus() {
    return {
        queueLength: unifiedAudioQueue.items.length,
        isPlaying: unifiedAudioQueue.isPlaying,
        currentItem: unifiedAudioQueue.currentItem,
        nextItems: unifiedAudioQueue.items.slice( 0, 3 ).map( item => ({
            type: item.type,
            priority: item.priority,
            preview: item.content.substring ? item.content.substring( 0, 50 ) + "..." : item.content
        }))
    };
}

// Legacy wrapper
function getTTSQueueStatus() {
    const ttsItems = unifiedAudioQueue.items.filter( item => item.type === 'tts' );
    return {
        queueLength: ttsItems.length,
        isPlaying: unifiedAudioQueue.isPlaying && unifiedAudioQueue.currentItem?.type === 'tts',
        nextMessages: ttsItems.slice( 0, 3 ).map( item => ({
            priority: item.priority,
            preview: item.content.substring( 0, 50 ) + "..."
        }))
    };
}

// Update queue display in UI
function updateQueueDisplay() {
    const statusElement = document.getElementById( "tts-queue-status" );
    if ( !statusElement ) return;
    
    const queueLength = unifiedAudioQueue.items.length;
    const playing = unifiedAudioQueue.isPlaying;
    
    if ( playing && unifiedAudioQueue.currentItem ) {
        statusElement.textContent = `Playing ${unifiedAudioQueue.currentItem.type}... (${queueLength} queued)`;
        statusElement.style.color = "#007bff"; // Blue
    } else if ( queueLength > 0 ) {
        statusElement.textContent = `${queueLength} items queued - click 'Play All' to hear them`;
        statusElement.style.color = "#fd7e14"; // Orange
    } else {
        statusElement.textContent = "No items queued";
        statusElement.style.color = "#6c757d"; // Gray
    }
}

// Legacy wrapper
function updateTTSQueueStatus() {
    updateQueueDisplay();
}

// Legacy: Store job completion messages for replay (replaced by JobCompletionCache)
// var jobCompletionMessages = new Map(); // jobId -> { text, timestamp } - DEPRECATED

// Authentication helpers
function getCurrentUserEmail() {
    const userEmailInput = document.getElementById( "user-email-input" );
    return userEmailInput ? userEmailInput.value.trim() : "ricardo.felipe.ruiz@gmail.com";
}

// Email-only approach: JavaScript never generates system IDs
// The server handles all email → system ID conversions internally

function getCurrentUserInfo() {
    const email = getCurrentUserEmail();
    
    // Extract display name from email (first part before any dots or special chars)
    const namePart = email.split( '@' )[0].split( '.' )[0];
    const displayName = namePart.charAt( 0 ).toUpperCase() + namePart.slice( 1 );
    
    return {
        email: email,
        name: displayName
    };
}

function getAuthHeader() {
    const email = getCurrentUserEmail();
    // Use email directly as the identifier
    return `Bearer mock_token_email_${email}`;
}

function updateAuthStatus() {
    const statusElement = document.getElementById( "auth-status" );
    const systemIdDisplay = document.getElementById( "system-id-display" );
    const userInfo = getCurrentUserInfo();
    
    if ( statusElement ) {
        statusElement.textContent = `✓ Authenticated as: ${userInfo.name}`;
        statusElement.style.color = userInfo.email ? "#28a745" : "#dc3545";
    }
    
    if ( systemIdDisplay ) {
        // Show email instead of system ID in email-only approach
        systemIdDisplay.textContent = userInfo.email;
    }
}

function updateWebSocketDebugInfo( sessionId, status, authToken ) {
    const sessionElement = document.getElementById( "websocket-session-id" );
    const statusElement = document.getElementById( "websocket-status" );
    const tokenElement = document.getElementById( "websocket-auth-token" );
    
    if ( sessionElement ) {
        sessionElement.textContent = sessionId || "Unknown";
    }
    
    if ( statusElement ) {
        statusElement.textContent = status || "Unknown";
        // Color coding for status
        if ( status.includes( "✓" ) || status.includes( "Authenticated" ) ) {
            statusElement.style.color = "#28a745"; // Green
        } else if ( status.includes( "✗" ) || status.includes( "Failed" ) ) {
            statusElement.style.color = "#dc3545"; // Red
        } else if ( status.includes( "Connecting" ) ) {
            statusElement.style.color = "#ffc107"; // Yellow
        } else {
            statusElement.style.color = "#6c757d"; // Gray
        }
    }
    
    if ( tokenElement ) {
        // Truncate long tokens for display
        const displayToken = authToken && authToken.length > 50 ? 
            authToken.substring( 0, 47 ) + "..." : 
            authToken || "None";
        tokenElement.textContent = displayToken;
    }
}

function handleNotificationSound( data ) {
    console.log( "Received notification_sound_update:", data );
    let url = data.soundFile;
    console.log( `Adding audio url to unified queue: ${ url }` );
    addToAudioQueue( 'audio', url, 'medium' );
}

// Handle server notifications to play audio with HybridTTS
async function handleAudioUpdate( data ) {
    console.log( "Received audio update:", data );
    
    // Use HybridTTS for all text-to-speech conversion
    if ( data.text ) {
        console.log( `Converting text to speech via HybridTTS: "${data.text}"` );
        
        try {
            if ( window.hybridTTS ) {
                await window.hybridTTS.speak( data.text );
            } else {
                console.error( "HybridTTS not available for audio conversion" );
            }
        } catch ( error ) {
            console.error( `Error in HybridTTS:`, error );
        }
        return;
    }
    
    // Legacy: Check if we have job completion text for local TTS
    if ( data.text && hybridTTS ) {
        console.log( `Playing job completion audio via TTS: "${data.text}"` );
        
        // Store the message for replay using advanced cache
        const jobId = `job_${Date.now()}`;
        const userEmail = getCurrentUserEmail();
        const timestamp = data.timestamp || new Date().toISOString();
        
        // Use advanced cache if available, fallback to simple storage
        if ( jobCache ) {
            await jobCache.store( jobId, data.text, timestamp, userEmail, {
                source: 'websocket_audio_update',
                audioGenerated: true
            });
            console.log( `Stored job completion message with ID: ${jobId} (advanced cache)` );
        } else {
            // Fallback to simple storage if cache not available
            if ( !window.fallbackJobMessages ) {
                window.fallbackJobMessages = new Map();
            }
            window.fallbackJobMessages.set( jobId, {
                text: data.text,
                timestamp: timestamp,
                jobId: jobId,
                userEmail: userEmail
            });
            console.log( `Stored job completion message with ID: ${jobId} (fallback storage)` );
        }
        
        try {
            await hybridTTS.speak( data.text );
            
            // Update the done list to show the new job with replay button
            addJobToCompletedList( jobId, data.text );
            
        } catch ( error ) {
            console.error( 'TTS failed, falling back to notification sound:', error );
            fallbackToNotificationSound();
        }
        return;
    }
    
    // Fall back to unified audio queue for URLs/notification sounds
    let url;
    if ( quiet ) {
        console.log( `Quiet mode, using gentle gong` );
        url = "/static/audio/gentle-gong.mp3";
    } else {
        if ( data.audioURL ) {
            url = data.audioURL;
        } else {
            url = "/static/audio/gentle-gong.mp3";
        }
    }
    
    // Avoid duplicate audio
    if ( lastAudioURL === url ) {
        console.log( "Same audio URL, not adding to queue" );
        return;
    }
    
    console.log( "Last audio URL:", lastAudioURL );
    console.log( " New audio URL:", url );
    lastAudioURL = url;

    console.log( `Adding audio url to unified queue: ${ url }` );
    addToAudioQueue( 'audio', url, 'medium' );
}

// Fallback function for when TTS fails
function fallbackToNotificationSound() {
    console.log( 'Playing fallback error notification sound for TTS failure' );
    
    // Use the error notification sound for TTS failures
    playNotificationSoundByPriority( "error" );
}

// Handle Claude Code notifications from the /api/notify endpoint
async function handleUserNotification( data ) {
    console.log( "Received Claude Code notification:", data );
    
    const { message, type, priority, source, timestamp } = data;
    
    // Create formatted notification message for TTS
    let ttsMessage = `${type} notification: ${message}`;
    
    // Add priority prefix for urgent/high priority notifications
    if ( priority === "urgent" ) {
        ttsMessage = `Urgent! ${ttsMessage}`;
    } else if ( priority === "high" ) {
        ttsMessage = `Important! ${ttsMessage}`;
    }
    
    console.log( `Playing Claude Code notification via TTS: "${ttsMessage}"` );
    
    // Use HybridTTS for audio notification if available
    if ( hybridTTS ) {
        try {
            await hybridTTS.speak( ttsMessage );
            console.log( `Successfully played Claude Code notification: ${type}/${priority}` );
        } catch ( error ) {
            console.error( 'TTS failed for Claude Code notification, using fallback sound:', error );
            fallbackToNotificationSound();
        }
    } else {
        console.log( 'HybridTTS not available, using fallback notification sound' );
        fallbackToNotificationSound();
    }
    
    // Optional: Show visual notification in the UI
    showVisualNotification( message, type, priority );
}

// Handle Claude Code notifications and add to notifications list  
async function handleClaudeCodeNotification( data ) {
    console.log( "Received Claude Code notification for list:", data );
    
    const { message, type, priority, source, timestamp } = data;
    
    // Add to notifications list
    addNotificationToList( data );
    
    // Create formatted notification message for TTS
    let ttsMessage = `${type} notification: ${message}`;
    
    // Add priority prefix for urgent/high priority notifications
    if ( priority === "urgent" ) {
        ttsMessage = `Urgent! ${ttsMessage}`;
    } else if ( priority === "high" ) {
        ttsMessage = `Important! ${ttsMessage}`;
    }
    
    console.log( `Queuing Claude Code notification for TTS: "${ttsMessage}"` );
    
    // Queue TTS message for synchronized playback
    await queueTTSMessage( ttsMessage, priority );
    
    // Show visual notification popup
    showVisualNotification( message, type, priority );
}

// Show visual notification in the UI (optional enhancement)
function showVisualNotification( message, type, priority ) {
    // Create a temporary visual notification element
    const notification = document.createElement( 'div' );
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        border-radius: 5px;
        color: white;
        font-weight: bold;
        z-index: 1000;
        max-width: 300px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: opacity 0.3s ease;
    `;
    
    // Set color based on priority
    switch( priority ) {
        case "urgent":
            notification.style.backgroundColor = "#dc3545"; // Red
            break;
        case "high":
            notification.style.backgroundColor = "#fd7e14"; // Orange
            break;
        case "medium":
            notification.style.backgroundColor = "#20c997"; // Teal
            break;
        case "low":
            notification.style.backgroundColor = "#6c757d"; // Gray
            break;
        default:
            notification.style.backgroundColor = "#007bff"; // Blue
    }
    
    // Set notification content
    const truncatedMessage = message.length > 100 ? message.substring(0, 97) + "..." : message;
    notification.innerHTML = `
        <div style="font-size: 12px; opacity: 0.8; margin-bottom: 5px;">
            Claude Code ${type.toUpperCase()} (${priority})
        </div>
        <div style="font-size: 14px;">
            ${truncatedMessage}
        </div>
    `;
    
    // Add to page
    document.body.appendChild( notification );
    
    // Auto-remove after delay (longer for higher priority)
    const displayTime = priority === "urgent" ? 10000 : 
                       priority === "high" ? 7000 : 
                       priority === "medium" ? 5000 : 3000;
    
    setTimeout( () => {
        notification.style.opacity = '0';
        setTimeout( () => {
            if ( notification.parentNode ) {
                document.body.removeChild( notification );
            }
        }, 300 );
    }, displayTime );
    
    console.log( `Visual notification displayed for ${displayTime}ms: ${type}/${priority}` );
}

// Add notification to the notifications list in the queue UI
function addNotificationToList( data ) {
    const { message, type, priority, source, timestamp } = data;
    const notificationsList = document.getElementById( "notifications-list" );
    const notificationsCounter = document.getElementById( "notifications" );
    
    if ( !notificationsList ) {
        console.error( "Notifications list element not found" );
        return;
    }
    
    // Format timestamp for display
    const time = new Date( timestamp ).toLocaleTimeString();
    
    // Create priority emoji and styling
    let priorityEmoji = "📝";
    let priorityColor = "#6c757d"; // Gray
    let typeEmoji = "📋";
    
    switch( priority ) {
        case "urgent":
            priorityEmoji = "🚨";
            priorityColor = "#dc3545"; // Red
            break;
        case "high":
            priorityEmoji = "⚡";
            priorityColor = "#fd7e14"; // Orange
            break;
        case "medium":
            priorityEmoji = "📢";
            priorityColor = "#20c997"; // Teal
            break;
        case "low":
            priorityEmoji = "💬";
            priorityColor = "#6c757d"; // Gray
            break;
    }
    
    switch( type ) {
        case "task":
            typeEmoji = "✅";
            break;
        case "progress":
            typeEmoji = "⏳";
            break;
        case "alert":
            typeEmoji = "⚠️";
            break;
        case "custom":
            typeEmoji = "💡";
            break;
    }
    
    // Truncate long messages for list display
    const displayMessage = message.length > 80 ? message.substring(0, 77) + "..." : message;
    
    // Use the server-provided id_hash for proper identification
    const notificationId = data.id_hash || `notification_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    console.log( `Adding notification to list with ID: "${notificationId}"` );
    
    // Create list item
    const listItem = document.createElement( "li" );
    listItem.id = notificationId;
    listItem.style.marginBottom = "8px";
    listItem.style.padding = "5px";
    listItem.style.borderLeft = `3px solid ${priorityColor}`;
    listItem.style.backgroundColor = "#f8f9fa";
    listItem.innerHTML = `
        <div style="display: flex; align-items: center; font-size: 12px;">
            <span style="margin-right: 5px;">${typeEmoji}</span>
            <span style="margin-right: 5px; color: ${priorityColor}; font-weight: bold;">${priorityEmoji}</span>
            <span style="color: #666; margin-right: 10px;">[${time}]</span>
            <span style="color: ${priorityColor}; font-weight: bold; margin-right: 5px;">${type.toUpperCase()}</span>
            <span style="color: ${priorityColor}; font-size: 10px; margin-right: 10px;">(${priority})</span>
            <span class="replay-notification" data-notification-id="${notificationId}" 
                  style="cursor: pointer; margin-left: auto; margin-right: 8px; opacity: 0.7; transition: opacity 0.2s; font-size: 14px;" 
                  title="Replay notification audio">🔊</span>
            <span class="delete-notification" data-notification-id="${notificationId}" 
                  style="cursor: pointer; opacity: 0.6; transition: opacity 0.2s; font-size: 14px; color: #dc3545;" 
                  title="Delete notification">🗑️</span>
        </div>
        <div style="margin-top: 2px; margin-left: 30px; font-size: 13px;" title="${message}">
            ${displayMessage}
        </div>
    `;
    
    // Add event listeners instead of onclick attributes
    const replayButton = listItem.querySelector( '.replay-notification' );
    if ( replayButton ) {
        replayButton.addEventListener( 'click', () => {
            console.log( `Replay clicked for: ${notificationId}` );
            replayNotificationAudio( notificationId );
        });
    }
    
    const deleteButton = listItem.querySelector( '.delete-notification' );
    if ( deleteButton ) {
        deleteButton.addEventListener( 'click', () => {
            console.log( `Delete clicked for: ${notificationId}` );
            deleteNotification( notificationId );
        });
    }
    
    // Store notification data for replay
    listItem.notificationData = {
        message: message,
        type: type,
        priority: priority,
        source: source,
        timestamp: timestamp,
        ttsMessage: `${priority === "urgent" ? "Urgent! " : priority === "high" ? "Important! " : ""}${type} notification: ${message}`
    };
    
    // Add to top of list (newest first)
    notificationsList.insertBefore( listItem, notificationsList.firstChild );
    
    // Update counter
    const currentCount = notificationsList.children.length;
    if ( notificationsCounter ) {
        notificationsCounter.textContent = `Claude Code Notifications: ${currentCount}`;
    }
    
    console.log( `Added ${type}/${priority} notification to list: "${displayMessage}"` );
}

// Replay notification audio from cached data
async function replayNotificationAudio( notificationId ) {
    const listItem = document.getElementById( notificationId );
    if ( !listItem || !listItem.notificationData ) {
        console.error( `No notification data found for ID: ${notificationId}` );
        return;
    }
    
    const { ttsMessage, type, priority, message } = listItem.notificationData;
    
    console.log( `Replaying notification audio: "${ttsMessage}"` );
    
    // Queue the TTS message for replay (uses same priority system)
    await queueTTSMessage( ttsMessage, priority );
    
    // Optional: Briefly highlight the notification being replayed
    const originalBackground = listItem.style.backgroundColor;
    listItem.style.backgroundColor = "#e3f2fd";
    listItem.style.transition = "background-color 0.3s";
    
    setTimeout( () => {
        listItem.style.backgroundColor = originalBackground;
    }, 1000 );
    
    console.log( `Queued replay for ${type}/${priority} notification` );
}

// Delete a notification from both UI and server
async function deleteNotification( notificationId ) {
    console.log( `Delete button clicked for notification: ${notificationId}` );
    
    // COMMENTED OUT: Show confirmation dialog - browser confirm() has issues
    // try {
    //     const confirmDelete = window.confirm( "Are you sure you want to permanently delete this notification? This action cannot be undone." );
    //     if ( !confirmDelete ) {
    //         console.log( "User cancelled deletion" );
    //         return; // User cancelled deletion
    //     }
    //     console.log( `User confirmed deletion of notification: ${notificationId}` );
    // } catch ( error ) {
    //     console.error( "Confirmation dialog failed, proceeding without confirmation:", error );
    //     // Continue with deletion if confirm() fails
    // }
    
    console.log( `Proceeding with deletion of notification: ${notificationId} (confirmation disabled)` );
    
    try {
        // Remove from server
        const response = await fetch( `/api/notifications/${notificationId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                api_key: notificationState.apiKey
            })
        });
        
        if ( response.ok ) {
            const result = await response.json();
            console.log( "Notification deleted from server:", result );
        } else if ( response.status === 404 ) {
            console.log( `Notification ${notificationId} not found on server (already deleted), removing from UI anyway` );
        } else {
            console.error( `Server error deleting notification: ${response.status}` );
            // For non-404 errors, show user feedback but still continue with UI removal
            alert( `Server error (${response.status}) deleting notification, but removing from UI anyway.` );
        }
        
    } catch ( error ) {
        console.error( "Network error deleting notification:", error );
        alert( "Network error deleting notification, but removing from UI anyway." );
    }
    
    // ALWAYS remove from UI and cache, regardless of server response
    // If server says 404, the item doesn't exist there, so it shouldn't exist in UI either
    const listItem = document.getElementById( notificationId );
    if ( listItem ) {
        listItem.remove();
        
        // Update counter
        const notificationsList = document.getElementById( "notifications-list" );
        const notificationsCounter = document.getElementById( "notifications" );
        if ( notificationsList && notificationsCounter ) {
            const currentCount = notificationsList.children.length;
            notificationsCounter.textContent = `Claude Code Notifications: ${currentCount}`;
        }
        
        console.log( `Notification ${notificationId} removed from UI` );
    }
    
    // Remove from local cache
    notificationState.notifications = notificationState.notifications.filter( 
        n => n.id_hash !== notificationId 
    );
}

// Make deleteNotification available globally for onclick handlers
window.deleteNotification = deleteNotification;

// Simple test function to verify onclick works
function testDelete() {
    console.log( "TEST: Delete function called!" );
    alert( "Delete test function works!" );
}
window.testDelete = testDelete;

// Add a completed job to the done list with replay button
// IMPORTANT: This function is only for testing/demo mock jobs.
// Real COSA jobs are displayed via updateQueueLists() and should NEVER be auto-deleted.
// Only manual deletion via 🗑️ button should remove items from done/dead queues.
function addJobToCompletedList( jobId, text ) {
    const doneList = document.getElementById( "done-list" );
    if ( !doneList ) return;
    
    // Create a new list item with replay button (for test jobs only)
    const shortText = text.length > 50 ? text.substring(0, 47) + "..." : text;
    const listItem = document.createElement( "li" );
    listItem.id = `job-done-${jobId}`;
    listItem.innerHTML = `
        ✅ <span class='replay' onclick='replayJobAudio("${jobId}")' title='Replay audio: ${text}'>🔊</span> 
        Complete: ${shortText} [TEST]
        <span class='delete' onclick='deleteCompletedJob("${jobId}")'>🗑️</span>
    `;
    
    // Add to the top of the list (most recent first)
    doneList.insertBefore( listItem, doneList.firstChild );
    
    // Update the done counter
    const doneCount = doneList.children.length;
    document.getElementById( "done" ).innerHTML = `Jobs done: ${doneCount}`;
    
    console.log( `Added job ${jobId} to completed list` );
}

// Replay job completion audio
async function replayJobAudio( jobId ) {
    let jobData = null;
    
    // Try advanced cache first
    if ( jobCache ) {
        jobData = await jobCache.get( jobId );
    }
    
    // Fallback to simple storage if cache not available or job not found
    if ( !jobData && window.fallbackJobMessages ) {
        jobData = window.fallbackJobMessages.get( jobId );
    }
    
    if ( !jobData ) {
        console.error( `No job data found for ID: ${jobId}` );
        return;
    }
    
    console.log( `Replaying audio for job ${jobId}: "${jobData.text}"` );
    
    if ( hybridTTS ) {
        try {
            await hybridTTS.speak( jobData.text );
        } catch ( error ) {
            console.error( 'Replay TTS failed:', error );
            fallbackToNotificationSound();
        }
    } else {
        console.warn( 'HybridTTS not available, playing fallback sound' );
        fallbackToNotificationSound();
    }
}

// Delete a completed job from the list and memory
// IMPORTANT: This should ONLY be called manually by user clicking 🗑️ button.
// NEVER call this automatically - jobs should accumulate in done/dead queues as history.
async function deleteCompletedJob( jobId ) {
    const confirmDelete = confirm( "Are you sure you want to delete this completed job? This action cannot be undone." );
    if ( !confirmDelete ) {
        return; // User cancelled deletion
    }
    
    const listItem = document.getElementById( `job-done-${jobId}` );
    if ( listItem ) {
        listItem.remove();
        
        // Remove from storage (for test jobs only)
        if ( jobCache ) {
            await jobCache.delete( jobId );
        } else if ( window.fallbackJobMessages ) {
            window.fallbackJobMessages.delete( jobId );
        }
        
        // Update the done counter
        const doneList = document.getElementById( "done-list" );
        const doneCount = doneList ? doneList.children.length : 0;
        document.getElementById( "done" ).innerHTML = `Jobs done: ${doneCount}`;
        
        console.log( `MANUALLY deleted job ${jobId} from completed list` );
    }
}

async function playOne( audio ) {
    return new Promise(function(resolve, reject) {
        audio.onerror = reject;
        audio.onended = resolve;
        audio.play()
    });
}

// Legacy playAll function - now redirects to unified queue
async function playAll() {
    console.log( "Legacy playAll() called - redirecting to unified queue" );
    
    // If there are items in the old audioQueue, migrate them
    while ( audioQueue.length > 0 ) {
        const audio = audioQueue.shift();
        // Extract URL from audio element
        const url = audio.src || audio.getAttribute('src');
        if ( url ) {
            addToAudioQueue( 'audio', url, 'medium' );
        }
    }
    
    // Start the unified queue
    playQueue();
}

function pushQuestion() {
    var question = document.getElementById( "question-input" ).value;
    fetch( "/api/push?question=" + question )
        .then( response => {
            if ( response.status === 200 ) {
                document.getElementById( "response-status" ).textContent = "Success!";
            } else {
                document.getElementById( "response-status" ).textContent = "Error :-(";
                throw new Error( `HTTP error, status = ${ response.status }` );
            }
            return response.text();
        } )
        .then( ( text ) => {
            // document.getElementById( "response-text" ).textContent = text;
        } )
        .catch( error => console.error( "Error:", error ) );
}

function setEnterKeyListener() {
    const questionInput = document.getElementById( "question-input" );
    if ( questionInput ) {
        questionInput.addEventListener( "keyup", ({key}) => {
            if ( key === "Enter" ) {
                submitQuestion();
            }
        });
    }
}

// Test functions for manual replay testing
function testJobCompletion() {
    const testMessages = [
        "Your test calculation has been completed successfully.",
        "The test query has finished processing.",
        "Your test request is now complete.",
        "The test analysis has been finished.",
        "Test job completed with excellent results."
    ];
    
    const randomMessage = testMessages[Math.floor(Math.random() * testMessages.length)];
    
    // Simulate an audio_update event
    handleAudioUpdate({
        text: randomMessage,
        timestamp: new Date().toISOString()
    });
}

async function clearCompletedJobs() {
    const doneList = document.getElementById( "done-list" );
    if ( doneList ) {
        // Remove all job completion items (keep any existing mock items)
        const jobItems = doneList.querySelectorAll( '[id^="job-done-"]' );
        jobItems.forEach( item => item.remove() );
        
        // Clear the messages storage
        if ( jobCache ) {
            // Only clear user's own jobs for advanced cache
            const userEmail = getCurrentUserEmail();
            const userJobs = await jobCache.getAllJobs( userEmail );
            for ( const job of userJobs ) {
                if ( job.jobId.startsWith( 'job-done-' ) ) {
                    await jobCache.delete( job.jobId );
                }
            }
        } else if ( window.fallbackJobMessages ) {
            window.fallbackJobMessages.clear();
        }
        
        // Update counter
        const remainingCount = doneList.children.length;
        document.getElementById( "done" ).innerHTML = `Jobs done: ${remainingCount}`;
        
        console.log( 'Cleared all completed jobs' );
    }
}

// Show cache analytics for both HybridTTS and JobCompletionCache
function showCacheAnalytics() {
    let analyticsHTML = '<h3>Cache Analytics</h3>';
    
    // HybridTTS Analytics
    if ( hybridTTS && typeof hybridTTS.getAnalytics === 'function' ) {
        const ttsAnalytics = hybridTTS.getAnalytics();
        analyticsHTML += `
            <h4>HybridTTS Audio Cache</h4>
            <ul>
                <li>Total Requests: ${ttsAnalytics.totalRequests}</li>
                <li>Cache Hits: ${ttsAnalytics.cacheHits}</li>
                <li>Cache Misses: ${ttsAnalytics.cacheMisses}</li>
                <li>Hit Rate: ${ttsAnalytics.hitRate}</li>
                <li>Cache Size: ${ttsAnalytics.totalCacheSize}</li>
                <li>Cached Items: ${ttsAnalytics.cacheEntries}</li>
            </ul>`;
        
        if ( ttsAnalytics.popularPhrases && ttsAnalytics.popularPhrases.length > 0 ) {
            analyticsHTML += '<h5>Popular Phrases (Audio)</h5><ol>';
            ttsAnalytics.popularPhrases.forEach( phrase => {
                analyticsHTML += `<li>${phrase.phrase} (${phrase.count}x)</li>`;
            });
            analyticsHTML += '</ol>';
        }
    } else {
        analyticsHTML += '<h4>HybridTTS Audio Cache</h4><p>Not available or not initialized</p>';
    }
    
    // JobCompletionCache Analytics
    if ( jobCache && typeof jobCache.getAnalytics === 'function' ) {
        const jobAnalytics = jobCache.getAnalytics();
        analyticsHTML += `
            <h4>Job Completion Message Cache</h4>
            <ul>
                <li>Total Stores: ${jobAnalytics.totalStores}</li>
                <li>Total Retrieves: ${jobAnalytics.totalRetrieves}</li>
                <li>Cache Hits: ${jobAnalytics.cacheHits}</li>
                <li>Cache Misses: ${jobAnalytics.cacheMisses}</li>
                <li>Hit Rate: ${jobAnalytics.hitRate}</li>
                <li>Cache Size: ${jobAnalytics.totalCacheSize}</li>
                <li>Cached Jobs: ${jobAnalytics.cacheEntries}</li>
            </ul>`;
            
        if ( jobAnalytics.popularPhrases && jobAnalytics.popularPhrases.length > 0 ) {
            analyticsHTML += '<h5>Popular Phrases (Messages)</h5><ol>';
            jobAnalytics.popularPhrases.forEach( phrase => {
                analyticsHTML += `<li>${phrase.phrase} (${phrase.count}x)</li>`;
            });
            analyticsHTML += '</ol>';
        }
        
        if ( jobAnalytics.topJobs && jobAnalytics.topJobs.length > 0 ) {
            analyticsHTML += '<h5>Most Replayed Jobs</h5><ol>';
            jobAnalytics.topJobs.forEach( job => {
                analyticsHTML += `<li>${job.jobId} (${job.replayCount}x)</li>`;
            });
            analyticsHTML += '</ol>';
        }
    } else {
        analyticsHTML += '<h4>Job Completion Message Cache</h4><p>Not available or not initialized</p>';
    }
    
    // Create a popup window to display analytics
    const popup = window.open( '', 'CacheAnalytics', 'width=600,height=800,scrollbars=yes' );
    popup.document.write( `
        <html>
            <head>
                <title>Cache Analytics</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    h3 { color: #333; border-bottom: 2px solid #007bff; }
                    h4 { color: #007bff; margin-top: 20px; }
                    h5 { color: #666; margin-top: 15px; }
                    ul { background: #f8f9fa; padding: 10px; border-radius: 5px; }
                    ol { background: #e9ecef; padding: 10px; border-radius: 5px; }
                    li { margin: 5px 0; }
                </style>
            </head>
            <body>
                ${analyticsHTML}
                <button onclick="window.close()" style="margin-top: 20px; padding: 10px 20px;">Close</button>
            </body>
        </html>
    ` );
}

// ============================================================================
// Notification State Management (Client-Side Integration with NotificationFifoQueue)
// ============================================================================

// State management for server-side notifications
var notificationState = {
    apiKey: "claude_code_simple_key",
    userId: null, // Will be set from auth
    notifications: [], // Local cache of notifications
    lastSync: null
};

// Initialize notification state management
function initializeNotificationState() {
    // Get user email for logging
    const userEmail = getCurrentUserEmail();
    if ( userEmail ) {
        console.log( `Notification state initialized for user: ${userEmail}` );
        console.log( "User ID will be set when WebSocket authenticates, then notifications will load" );
    } else {
        console.log( "User not authenticated - notification state not initialized" );
    }
}

// Convert email to system ID (client-side implementation)
function emailToSystemId( email ) {
    // Simple hash-based system ID generation to match server-side logic
    // This should match the email_to_system_id function in the server
    return btoa( email ).replace(/[^a-zA-Z0-9]/g, '').substring( 0, 12 ).toLowerCase();
}

// Load initial notifications from server (one-time, no polling)
async function loadInitialNotifications() {
    if ( !notificationState.userId ) {
        console.log( "Cannot load notifications - user not authenticated" );
        return;
    }
    
    try {
        const response = await fetch( `/api/notifications/${notificationState.userId}?include_played=true&api_key=${notificationState.apiKey}` );
        
        if ( !response.ok ) {
            console.error( "Failed to load initial notifications:", response.status, response.statusText );
            return;
        }
        
        const data = await response.json();
        const serverNotifications = data.notifications || [];
        
        console.log( `Loaded ${serverNotifications.length} notifications from server (played and unplayed)` );
        
        // Just populate the local cache, don't auto-play old notifications
        notificationState.notifications = serverNotifications;
        
        // Update UI with existing notifications
        serverNotifications.forEach( notification => {
            addNotificationToList( notification );
        });
        
        notificationState.lastSync = new Date().toISOString();
        
    } catch ( error ) {
        console.error( "Error loading initial notifications:", error );
    }
}

// Process a notification from the server queue
async function processServerNotification( notification ) {
    console.log( "Processing server notification:", notification );
    
    const { message, type, priority, id_hash } = notification;
    
    // 1. ALWAYS play notification sound first based on priority
    await playNotificationSoundByPriority( priority );
    
    // 2. Check TTS auto-play settings
    const ttsAutoplayToggle = document.getElementById( "tts-autoplay-toggle" );
    const ttsAutoplayEnabled = ttsAutoplayToggle ? ttsAutoplayToggle.checked : true;
    
    console.log( `[TTS-AUTO] Toggle element found: ${!!ttsAutoplayToggle}` );
    console.log( `[TTS-AUTO] Toggle checked: ${ttsAutoplayToggle ? ttsAutoplayToggle.checked : 'N/A'}` );
    console.log( `[TTS-AUTO] Auto-play enabled: ${ttsAutoplayEnabled}` );
    console.log( `[TTS-AUTO] Priority: ${priority}, will auto-play: ${ttsAutoplayEnabled && ( priority === "high" || priority === "urgent" )}` );
    
    // 3. Only queue TTS for high priority notifications when auto-play is enabled
    if ( ttsAutoplayEnabled && ( priority === "high" || priority === "urgent" ) ) {
        // Create formatted notification message for TTS
        let ttsMessage = `${type} notification: ${message}`;
        
        // Add priority prefix for urgent/high priority notifications
        if ( priority === "urgent" ) {
            ttsMessage = `Urgent! ${ttsMessage}`;
        } else if ( priority === "high" ) {
            ttsMessage = `Important! ${ttsMessage}`;
        }
        
        console.log( `Queuing high priority notification for TTS playback: "${ttsMessage}"` );
        
        // Add to unified audio queue for playback (slight delay to let notification sound finish)
        setTimeout( () => queueTTSMessage( ttsMessage, priority ), 300 );
    } else {
        console.log( `Skipping TTS for ${priority} priority notification (auto-play: ${ttsAutoplayEnabled})` );
    }
    
    // Show visual notification
    showVisualNotification( message, type, priority );
    
    // Add to notifications list
    addNotificationToList( notification );
    
    // Mark as played on server after successful processing
    setTimeout( () => markNotificationAsPlayed( id_hash ), 1000 );
}

// Mark notification as played on server
async function markNotificationAsPlayed( notificationId ) {
    try {
        const response = await fetch( `/api/notifications/${notificationId}/played?api_key=${notificationState.apiKey}`, {
            method: 'POST'
        });
        
        if ( response.ok ) {
            console.log( `Marked notification ${notificationId} as played on server` );
            
            // Update local cache
            const notification = notificationState.notifications.find( n => n.id_hash === notificationId );
            if ( notification ) {
                notification.played = true;
                notification.play_count = ( notification.play_count || 0 ) + 1;
                notification.last_played = new Date().toISOString();
            }
        } else {
            console.error( `Failed to mark notification ${notificationId} as played:`, response.status );
        }
        
    } catch ( error ) {
        console.error( `Error marking notification ${notificationId} as played:`, error );
    }
}

// Get next unplayed notification from server
async function getNextNotificationFromServer() {
    if ( !notificationState.userId ) {
        return null;
    }
    
    try {
        const response = await fetch( `/api/notifications/${notificationState.userId}/next?api_key=${notificationState.apiKey}` );
        
        if ( !response.ok ) {
            console.error( "Failed to get next notification:", response.status );
            return null;
        }
        
        const data = await response.json();
        return data.status === "success" ? data.notification : null;
        
    } catch ( error ) {
        console.error( "Error getting next notification:", error );
        return null;
    }
}

// Get notification state for debugging
function getNotificationState() {
    return {
        userId: notificationState.userId,
        notificationCount: notificationState.notifications.length,
        lastSync: notificationState.lastSync,
        unplayedCount: notificationState.notifications.filter( n => !n.played ).length
    };
}

// Handle real-time notification updates via WebSocket
async function handleNotificationUpdate( data ) {
    console.log( "Received notification_update WebSocket event:", data );
    
    const notification = data.notification;
    if ( !notification ) {
        console.log( "No notification data in WebSocket event" );
        return;
    }
    
    // Check if we've already processed this notification
    const exists = notificationState.notifications.find( n => n.id_hash === notification.id_hash );
    if ( exists ) {
        console.log( `Notification ${notification.id_hash} already processed - ignoring duplicate` );
        return;
    }
    
    // New notification - add to local cache
    notificationState.notifications.push( notification );
    console.log( `Processing new notification: ${notification.type}/${notification.priority} - ${notification.message}` );
    
    // Process it immediately for auto-play (server already filtered by user)
    await processServerNotification( notification );
}

// Reset all queues via API endpoint
async function resetAllQueues() {
    if ( !confirm( "Are you sure you want to reset ALL queues? This will clear todo, running, done, dead, and notification queues. This action cannot be undone." ) ) {
        return;
    }
    
    console.log( "Resetting all queues..." );
    
    try {
        const response = await fetch( "/api/reset-queues", {
            method: "POST",
            headers: {
                'Authorization': getAuthHeader(),
                'X-Session-ID': sessionId,
                'Content-Type': 'application/json'
            }
        });
        
        if ( response.ok ) {
            const result = await response.json();
            console.log( "Queue reset successful:", result );
            
            // Show success message
            alert( `✅ All queues reset successfully!\n\nCleared ${result.total_items_cleared} total items:\n- Todo: ${result.queues_reset.todo}\n- Running: ${result.queues_reset.run}\n- Done: ${result.queues_reset.done}\n- Dead: ${result.queues_reset.dead}\n- Notifications: ${result.queues_reset.notification}` );
            
            // Note: Queue displays will refresh automatically via WebSocket events from _emit_queue_update()
            console.log( "Queue displays will refresh automatically via WebSocket notifications" );
            
            // Clear any local job storage
            if ( window.fallbackJobMessages ) {
                window.fallbackJobMessages.clear();
                console.log( "Cleared fallback job messages storage" );
            }
            
            // Refresh notifications if available
            if ( typeof loadNotifications === 'function' ) {
                await loadNotifications();
                console.log( "Refreshed notifications display" );
            }
            
        } else {
            const errorText = await response.text();
            console.error( "Failed to reset queues:", response.status, errorText );
            alert( `❌ Failed to reset queues: ${response.status}\n${errorText}` );
        }
        
    } catch ( error ) {
        console.error( "Error calling reset-queues endpoint:", error );
        alert( `❌ Error resetting queues: ${error.message}` );
    }
}

// Initialize notification state when DOM is ready
document.addEventListener( "DOMContentLoaded", function() {
    // Delay initialization to allow auth system to load
    setTimeout( initializeNotificationState, 1000 );
});

// create a method that closes this window after escape has been hit 2 times in a row
var escapeCounter = 0;

window.addEventListener( "keydown", function( event ) {
    if ( event.key === "Escape" ) {
        escapeCounter++;
        if ( escapeCounter === 2 ) {
            window.close();
        }
    } else {
        escapeCounter = 0;
    }
} );