/**
 * Admin Snapshots Dashboard - JavaScript Logic
 *
 * Handles:
 * - JWT authentication and admin role verification
 * - Search functionality
 * - Results display
 * - View details modal
 * - Delete confirmation and execution
 */

// Admin Snapshots Dashboard
class AdminSnapshotsDashboard {
    constructor() {
        this.currentUser = null;
        this.isAdmin = false;
        this.searchResults = [];
        this.selectedSnapshotId = null;

        // STT for search input
        this.searchAudioRecorder = null;
        this.searchRecordingInterval = null;
        this.searchRecordingCancelListener = null;
    }

    async init() {
        // Check authentication
        await this.setupAuthentication();

        // Setup event listeners
        this.setupEventListeners();

        // Display user info
        this.displayUserInfo();

        // Auto-focus STT button for spacebar activation
        document.getElementById( 'search-stt-button' ).focus();
    }

    async setupAuthentication() {
        // Check if user is authenticated
        if ( !isAuthenticated() ) {
            window.location.href = '/static/html/auth/login.html?redirect=/static/html/admin/snapshots.html';
            return;
        }

        // Get current user data
        const userData = await getCurrentUser();

        if ( !userData ) {
            clearTokens();
            window.location.href = '/static/html/auth/login.html';
            return;
        }

        // Extract user info
        this.currentUser = userData.email;
        this.isAdmin = await hasRole( 'admin' );

        // Check admin role
        if ( !this.isAdmin ) {
            alert( 'Admin access required' );
            window.location.href = '/static/html/auth/profile.html';
            return;
        }
    }

    displayUserInfo() {
        document.getElementById( 'user-email' ).textContent = this.currentUser;
    }

    setupEventListeners() {
        // Search STT button click
        document.getElementById( 'search-stt-button' ).addEventListener( 'click', () => {
            this.handleSearchSTTButtonClick();
        });

        // Ctrl+R shortcut for search STT recording
        document.addEventListener( 'keydown', ( e ) => {
            if ( e.ctrlKey && e.key === 'r' ) {
                e.preventDefault();  // Prevent browser refresh
                this.handleSearchSTTButtonClick();
            }
        });

        // Search button
        document.getElementById( 'search-btn' ).addEventListener( 'click', () => {
            this.performSearch();
        });

        // Enter key in search input
        document.getElementById( 'search-input' ).addEventListener( 'keypress', ( e ) => {
            if ( e.key === 'Enter' ) {
                this.performSearch();
            }
        });

        // Logout button
        document.getElementById( 'logout-btn' ).addEventListener( 'click', () => {
            clearTokens();
            window.location.href = '/static/html/auth/login.html';
        });

        // Detail modal close buttons
        document.getElementById( 'close-detail-btn' ).addEventListener( 'click', () => {
            this.closeDetailModal();
        });

        document.querySelector( '#detail-modal .modal-overlay' ).addEventListener( 'click', () => {
            this.closeDetailModal();
        });

        // Delete modal close buttons
        document.getElementById( 'close-delete-btn' ).addEventListener( 'click', () => {
            this.closeDeleteModal();
        });

        document.getElementById( 'cancel-delete-btn' ).addEventListener( 'click', () => {
            this.closeDeleteModal();
        });

        document.querySelector( '#delete-modal .modal-overlay' ).addEventListener( 'click', () => {
            this.closeDeleteModal();
        });

        // Confirm delete button
        document.getElementById( 'confirm-delete-btn' ).addEventListener( 'click', () => {
            this.deleteSnapshot();
        });
    }

    async performSearch() {
        const query = document.getElementById( 'search-input' ).value.trim();

        if ( !query ) {
            this.showError( 'Please enter a search query' );
            return;
        }

        this.hideError();
        this.showLoading();

        try {
            const response = await this.apiCall( `/admin/snapshots/search?q=${encodeURIComponent( query )}` );

            this.searchResults = response.results;
            this.displayResults();
            this.updateResultsCount( response.total, query );

        } catch ( error ) {
            this.showError( `Search failed: ${error.message}` );
        } finally {
            this.hideLoading();
        }
    }

    async apiCall( endpoint, method = 'GET', data = null ) {
        const url = `${window.location.origin}${endpoint}`;
        const token = getAccessToken();

        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        };

        const options = { method, headers };
        if ( data && method !== 'GET' ) {
            options.body = JSON.stringify( data );
        }

        const response = await fetch( url, options );

        if ( !response.ok ) {
            if ( response.status === 401 ) {
                // Try refresh token
                const refreshed = await refreshAccessToken();
                if ( refreshed ) {
                    return this.apiCall( endpoint, method, data );
                }
                throw new Error( 'Authentication failed' );
            }

            const errorData = await response.json();
            throw new Error( errorData.detail || 'Request failed' );
        }

        return await response.json();
    }

    displayResults() {
        const tbody = document.getElementById( 'results-tbody' );
        tbody.innerHTML = '';

        if ( this.searchResults.length === 0 ) {
            document.getElementById( 'empty-state' ).style.display = 'block';
            document.getElementById( 'results-table' ).style.display = 'none';
            return;
        }

        document.getElementById( 'empty-state' ).style.display = 'none';
        document.getElementById( 'results-table' ).style.display = 'table';

        this.searchResults.forEach( result => {
            const row = this.createResultRow( result );
            tbody.appendChild( row );
        });
    }

    createResultRow( result ) {
        const row = document.createElement( 'tr' );

        // Match percentage (first column)
        const scoreCell = document.createElement( 'td' );
        scoreCell.className = 'match-score';
        const score = result.score || 0;
        scoreCell.textContent = `${score.toFixed( 1 )}%`;

        // Color-code based on match quality
        if ( score >= 100 ) {
            scoreCell.classList.add( 'exact-match' );
        } else if ( score >= 90 ) {
            scoreCell.classList.add( 'high-match' );
        } else if ( score >= 75 ) {
            scoreCell.classList.add( 'medium-match' );
        } else {
            scoreCell.classList.add( 'low-match' );
        }
        row.appendChild( scoreCell );

        // Question preview
        const questionCell = document.createElement( 'td' );
        questionCell.textContent = result.question_preview;
        questionCell.className = 'question-preview';
        row.appendChild( questionCell );

        // Gist
        const gistCell = document.createElement( 'td' );
        gistCell.textContent = result.question_gist;
        row.appendChild( gistCell );

        // Created date
        const dateCell = document.createElement( 'td' );
        dateCell.textContent = this.formatDate( result.created_date );
        row.appendChild( dateCell );

        // Actions
        const actionsCell = document.createElement( 'td' );
        actionsCell.className = 'actions-cell';

        // View button
        const viewBtn = document.createElement( 'button' );
        viewBtn.textContent = 'View';
        viewBtn.className = 'btn-small btn-primary';
        viewBtn.onclick = () => this.viewDetails( result.id_hash );
        actionsCell.appendChild( viewBtn );

        // Delete button
        const deleteBtn = document.createElement( 'button' );
        deleteBtn.textContent = 'Delete';
        deleteBtn.className = 'btn-small btn-danger';
        deleteBtn.onclick = () => this.confirmDelete( result.id_hash, result.question_preview );
        actionsCell.appendChild( deleteBtn );

        row.appendChild( actionsCell );

        return row;
    }

    formatDate( dateString ) {
        const date = new Date( dateString );
        return date.toLocaleString();
    }

    updateResultsCount( total, query ) {
        const countEl = document.getElementById( 'results-count' );
        countEl.textContent = `Found ${total} result${total !== 1 ? 's' : ''} for "${query}"`;
    }

    async viewDetails( idHash ) {
        try {
            const snapshot = await this.apiCall( `/admin/snapshots/${idHash}` );

            // Set modal title with verbatim question
            const modalTitle = document.getElementById( 'detail-modal-title' );
            modalTitle.textContent = `Snapshot Details: ${snapshot.question}`;
            modalTitle.title = snapshot.question;  // Full text on hover

            // Populate modal fields
            document.getElementById( 'detail-question-normalized' ).textContent = snapshot.question_normalized;
            document.getElementById( 'detail-question-gist' ).textContent = snapshot.question_gist;
            document.getElementById( 'detail-answer' ).textContent = snapshot.answer || 'No answer';
            document.getElementById( 'detail-answer-conversational' ).textContent = snapshot.answer_conversational || 'No conversational answer';

            // Populate synonyms section (BEFORE runtime stats in display)
            // Note: Both dicts are { text: score } - questions and gists are KEYS, scores are VALUES
            const synonymQuestions = snapshot.synonymous_questions || {};
            const synonymGists = snapshot.synonymous_question_gists || {};
            const questionKeys = Object.keys( synonymQuestions );
            const gistKeys = Object.keys( synonymGists );

            // Total count is max of questions and gists (they're typically paired by index)
            const totalCount = Math.max( questionKeys.length, gistKeys.length );
            document.getElementById( 'synonyms-count' ).textContent = totalCount;

            const synonymsList = document.getElementById( 'synonyms-list' );
            if ( totalCount === 0 ) {
                synonymsList.innerHTML = '<div class="no-synonyms">No synonyms recorded</div>';
            } else {
                // Pair questions with gists by index (they're added together)
                const pairs = [];
                for ( let i = 0; i < totalCount; i++ ) {
                    const question = questionKeys[i] || null;
                    const gist = gistKeys[i] || null;
                    const score = question ? synonymQuestions[question] : ( gist ? synonymGists[gist] : 0 );
                    pairs.push( { question, gist, score } );
                }

                synonymsList.innerHTML = pairs.map( pair => {
                    // Scores are already 0-100 percentages, no need to multiply
                    const scorePercent = pair.score.toFixed( 1 );
                    const questionHtml = pair.question
                        ? `<div class="synonym-question">${escapeHtml( pair.question )}</div>`
                        : '';
                    const gistHtml = pair.gist
                        ? `<div class="synonym-gist">${escapeHtml( pair.gist )}</div>`
                        : '';
                    return `
                        <div class="synonym-pair">
                            <span class="synonym-score">${scorePercent}%</span>
                            ${questionHtml}
                            ${gistHtml}
                        </div>
                    `;
                }).join( '' );
            }

            // Reset to collapsed state when opening new detail
            document.getElementById( 'synonyms-content' ).classList.add( 'collapsed' );
            document.getElementById( 'synonyms-toggle' ).textContent = '▶';

            // Format runtime statistics as pretty JSON
            const runtimeStats = snapshot.runtime_stats || {};
            const statsFormatted = JSON.stringify( runtimeStats, null, 2 );
            document.getElementById( 'detail-runtime-stats' ).textContent = statsFormatted;

            // Format executable code as multi-line string
            const code = snapshot.code || [];
            const codeFormatted = code.length > 0 ? code.join( '\n' ) : 'N/A';
            document.getElementById( 'detail-code' ).textContent = codeFormatted;

            document.getElementById( 'detail-id-hash' ).textContent = snapshot.id_hash;
            document.getElementById( 'detail-user-id' ).textContent = snapshot.user_id || 'N/A';
            document.getElementById( 'detail-created-date' ).textContent = this.formatDate( snapshot.created_date );

            // Show modal
            document.getElementById( 'detail-modal' ).style.display = 'flex';

        } catch ( error ) {
            this.showError( `Failed to load details: ${error.message}` );
        }
    }

    closeDetailModal() {
        document.getElementById( 'detail-modal' ).style.display = 'none';
    }

    confirmDelete( idHash, questionPreview ) {
        this.selectedSnapshotId = idHash;

        // Show preview in confirmation modal
        document.getElementById( 'delete-preview' ).textContent = questionPreview;

        // Show modal
        document.getElementById( 'delete-modal' ).style.display = 'flex';
    }

    async deleteSnapshot() {
        if ( !this.selectedSnapshotId ) return;

        try {
            await this.apiCall( `/admin/snapshots/${this.selectedSnapshotId}`, 'DELETE' );

            // Remove from results
            this.searchResults = this.searchResults.filter(
                r => r.id_hash !== this.selectedSnapshotId
            );

            // Refresh display
            this.displayResults();
            this.updateResultsCount( this.searchResults.length, document.getElementById( 'search-input' ).value );

            // Close modal
            this.closeDeleteModal();

        } catch ( error ) {
            this.showError( `Failed to delete snapshot: ${error.message}` );
            this.closeDeleteModal();
        }
    }

    closeDeleteModal() {
        document.getElementById( 'delete-modal' ).style.display = 'none';
        this.selectedSnapshotId = null;
    }

    showLoading() {
        document.getElementById( 'loading-state' ).style.display = 'block';
        document.getElementById( 'results-table' ).style.display = 'none';
        document.getElementById( 'empty-state' ).style.display = 'none';
    }

    hideLoading() {
        document.getElementById( 'loading-state' ).style.display = 'none';
    }

    showError( message ) {
        const errorEl = document.getElementById( 'search-error' );
        errorEl.textContent = message;
        errorEl.style.display = 'block';
    }

    hideError() {
        document.getElementById( 'search-error' ).style.display = 'none';
    }

    // ============================================================================
    // STT (Speech-to-Text) Methods for Search Input
    // ============================================================================

    async handleSearchSTTButtonClick() {
        const button = document.getElementById( 'search-stt-button' );

        // If already recording, stop it
        if ( this.searchAudioRecorder && this.searchAudioRecorder.isRecording ) {
            await this.searchAudioRecorder.stopRecording();
            return;
        }

        // If processing, ignore click
        if ( this.searchAudioRecorder && this.searchAudioRecorder.isProcessing ) {
            return;
        }

        // Start new recording
        await this.startSearchVoiceInput();
    }

    async startSearchVoiceInput() {
        const button = document.getElementById( 'search-stt-button' );
        const textInput = document.getElementById( 'search-input' );
        const authToken = getAccessToken();

        if ( !authToken ) {
            alert( 'Please log in to use voice input' );
            return;
        }

        try {
            // Create new AudioRecorder instance
            this.searchAudioRecorder = new AudioRecorder( {
                uploadEndpoint: '/api/upload-and-transcribe-mp3',
                authToken: authToken,

                onRecordingStart: () => {
                    button.classList.add( 'recording' );
                    button.textContent = '🔴';
                    this._startSearchDurationCounter( button );
                    this._attachSearchRecordingCancelListener( button );
                },

                onRecordingStop: ( audioBlob ) => {
                    this._stopSearchDurationCounter();
                    this._detachSearchRecordingCancelListener();
                    button.classList.remove( 'recording' );
                    button.classList.add( 'processing' );
                    button.textContent = '⏳';
                    button.disabled = true;
                },

                onTranscription: ( text ) => {
                    // Fill text input with transcription
                    textInput.value = text;
                    textInput.focus();
                    textInput.select();

                    // Reset button UI
                    button.classList.remove( 'processing' );
                    button.textContent = '🎤';
                    button.disabled = false;
                    this._detachSearchRecordingCancelListener();

                    // Auto-trigger search after transcription
                    this.performSearch();
                },

                onError: ( error ) => {
                    alert( `Recording error: ${error.message}` );

                    // Reset button UI
                    button.classList.remove( 'recording', 'processing' );
                    button.textContent = '🎤';
                    button.disabled = false;
                    this._detachSearchRecordingCancelListener();
                },

                debug: false
            } );

            await this.searchAudioRecorder.startRecording();

        } catch ( error ) {
            console.error( 'Failed to start search voice input:', error );
            alert( `Failed to start recording: ${error.message}` );

            // Reset UI
            button.classList.remove( 'recording', 'processing' );
            button.textContent = '🎤';
            button.disabled = false;
        }
    }

    _startSearchDurationCounter( button ) {
        const startTime = Date.now();
        const MAX_DURATION_SECONDS = 30;

        this.searchRecordingInterval = setInterval( () => {
            const elapsed = Math.floor( ( Date.now() - startTime ) / 1000 );
            const icon = elapsed >= 25 ? '🟡' : '🔴';
            button.textContent = `${icon} ${elapsed}/${MAX_DURATION_SECONDS}s`;
        }, 1000 );
    }

    _stopSearchDurationCounter() {
        if ( this.searchRecordingInterval ) {
            clearInterval( this.searchRecordingInterval );
            this.searchRecordingInterval = null;
        }
    }

    _attachSearchRecordingCancelListener( button ) {
        this.searchRecordingCancelListener = ( event ) => {
            if ( event.key === 'Escape' ) {
                event.preventDefault();
                event.stopPropagation();
                this._cancelSearchRecording( button );
            }
        };
        document.addEventListener( 'keydown', this.searchRecordingCancelListener );
    }

    _detachSearchRecordingCancelListener() {
        if ( this.searchRecordingCancelListener ) {
            document.removeEventListener( 'keydown', this.searchRecordingCancelListener );
            this.searchRecordingCancelListener = null;
        }
    }

    _cancelSearchRecording( button ) {
        // Stop duration counter
        this._stopSearchDurationCounter();

        // Destroy recorder without uploading
        if ( this.searchAudioRecorder ) {
            this.searchAudioRecorder._cancelling = true;  // Signal cancellation
            this.searchAudioRecorder.destroy();
            this.searchAudioRecorder = null;
        }

        // Reset UI
        button.classList.remove( 'recording', 'processing' );
        button.textContent = '🎤';
        button.disabled = false;
        this._detachSearchRecordingCancelListener();
    }
}

// ============================================================================
// Synonyms Toggle Function (global for onclick handler)
// ============================================================================

function toggleSynonyms() {
    const content = document.getElementById( 'synonyms-content' );
    const toggle = document.getElementById( 'synonyms-toggle' );

    if ( content.classList.contains( 'collapsed' ) ) {
        content.classList.remove( 'collapsed' );
        toggle.textContent = '▼';
    } else {
        content.classList.add( 'collapsed' );
        toggle.textContent = '▶';
    }
}

/**
 * Escape HTML entities to prevent XSS.
 */
function escapeHtml( text ) {
    const div = document.createElement( 'div' );
    div.textContent = text;
    return div.innerHTML;
}

// Initialize on page load
let dashboard;
document.addEventListener( 'DOMContentLoaded', () => {
    dashboard = new AdminSnapshotsDashboard();
    dashboard.init();
});
