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

        // Detail modal ESC key listener
        this.detailModalEscListener = null;

        // Similarity modal state
        this.similarityModalEscListener = null;
        this.currentDetailIdHash = null;  // Track which snapshot's detail modal is open
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

        // Find Similar button (in detail modal)
        document.getElementById( 'find-similar-btn' ).addEventListener( 'click', () => {
            if ( this.currentDetailIdHash ) {
                this.showSimilarSnapshots( this.currentDetailIdHash );
            }
        });

        // Similarity modal close buttons
        document.getElementById( 'close-similarity-btn' ).addEventListener( 'click', () => {
            this.closeSimilarityModal();
        });

        document.querySelector( '#similarity-modal .modal-overlay' ).addEventListener( 'click', () => {
            this.closeSimilarityModal();
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

        // Read filter values
        const threshold = document.getElementById( 'threshold-select' ).value;
        const limit = document.getElementById( 'limit-select' ).value;

        try {
            const response = await this.apiCall( `/admin/snapshots/search?q=${encodeURIComponent( query )}&threshold=${threshold}&limit=${limit}` );

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

        // Preview icons (code explanation + code)
        const previewCell = document.createElement( 'td' );
        previewCell.className = 'preview-icons';

        // Code explanation icon (📝)
        const gistIcon = document.createElement( 'span' );
        gistIcon.className = 'preview-icon';
        gistIcon.textContent = '📝';
        gistIcon.title = 'View code explanation';
        gistIcon.setAttribute( 'data-id', result.id_hash );
        gistIcon.onclick = ( e ) => {
            e.stopPropagation();
            this.showPreviewPopover( result.id_hash, 'gist', e.target );
        };
        previewCell.appendChild( gistIcon );

        // Code preview icon (💻)
        const codeIcon = document.createElement( 'span' );
        codeIcon.className = 'preview-icon';
        codeIcon.textContent = '💻';
        codeIcon.title = 'View code preview';
        codeIcon.setAttribute( 'data-id', result.id_hash );
        codeIcon.onclick = ( e ) => {
            e.stopPropagation();
            this.showPreviewPopover( result.id_hash, 'code', e.target );
        };
        previewCell.appendChild( codeIcon );

        row.appendChild( previewCell );

        // Created date
        const dateCell = document.createElement( 'td' );
        dateCell.textContent = this.formatDate( result.created_date );
        row.appendChild( dateCell );

        // ID hash (first 8 chars for compact display)
        const idCell = document.createElement( 'td' );
        idCell.className = 'id-hash';
        idCell.textContent = result.id_hash ? result.id_hash.substring( 0, 8 ) : '?';
        idCell.title = result.id_hash;  // Full hash on hover
        row.appendChild( idCell );

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

            // Store current ID hash for "Find Similar" button
            this.currentDetailIdHash = idHash;

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

            // Solution summary (verbose) and solution summary gist (concise)
            document.getElementById( 'detail-solution-summary' ).textContent = snapshot.solution_summary || 'N/A';
            document.getElementById( 'detail-solution-summary-gist' ).textContent = snapshot.solution_summary_gist || 'N/A';

            document.getElementById( 'detail-id-hash' ).textContent = snapshot.id_hash;
            document.getElementById( 'detail-user-id' ).textContent = snapshot.user_id || 'N/A';
            document.getElementById( 'detail-created-date' ).textContent = this.formatDate( snapshot.created_date );

            // Attach ESC key listener and show modal
            this._attachDetailModalEscListener();
            document.getElementById( 'detail-modal' ).style.display = 'flex';

        } catch ( error ) {
            this.showError( `Failed to load details: ${error.message}` );
        }
    }

    closeDetailModal() {
        this._detachDetailModalEscListener();
        document.getElementById( 'detail-modal' ).style.display = 'none';
        this.currentDetailIdHash = null;
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

    // ============================================================================
    // Detail Modal ESC Key Handler
    // ============================================================================

    _attachDetailModalEscListener() {
        this.detailModalEscListener = ( event ) => {
            if ( event.key === 'Escape' ) {
                event.preventDefault();
                event.stopPropagation();
                this.closeDetailModal();
            }
        };
        document.addEventListener( 'keydown', this.detailModalEscListener );
    }

    _detachDetailModalEscListener() {
        if ( this.detailModalEscListener ) {
            document.removeEventListener( 'keydown', this.detailModalEscListener );
            this.detailModalEscListener = null;
        }
    }

    // ============================================================================
    // Preview Popover (Phase 3: Code Similarity Visualization)
    // ============================================================================

    /**
     * Show preview popover for code or explanation.
     *
     * @param {string} idHash - Snapshot ID hash
     * @param {string} type - 'code' or 'gist'
     * @param {HTMLElement} anchorElement - Element to position popover near
     */
    async showPreviewPopover( idHash, type, anchorElement ) {
        // Close any existing popover
        this.closePreviewPopover();

        // Mark icon as loading
        anchorElement.classList.add( 'loading' );

        try {
            // Fetch preview data from API
            const preview = await this.apiCall( `/admin/snapshots/${idHash}/preview` );

            // Create popover
            const popover = this.createPreviewPopover( preview, type );

            // Position popover near anchor element
            this.positionPopover( popover, anchorElement );

            // Add to document
            document.body.appendChild( popover );

            // Add overlay to close on outside click
            const overlay = document.createElement( 'div' );
            overlay.className = 'preview-popover-overlay';
            overlay.onclick = () => this.closePreviewPopover();
            document.body.appendChild( overlay );

            // Store references for cleanup
            this._currentPopover = popover;
            this._currentPopoverOverlay = overlay;

            // Add ESC key listener
            this._popoverEscListener = ( event ) => {
                if ( event.key === 'Escape' ) {
                    this.closePreviewPopover();
                }
            };
            document.addEventListener( 'keydown', this._popoverEscListener );

        } catch ( error ) {
            console.error( 'Failed to fetch preview:', error );
            // Show error tooltip briefly
            anchorElement.title = 'Failed to load preview';
        } finally {
            anchorElement.classList.remove( 'loading' );
        }
    }

    /**
     * Create the popover DOM element.
     */
    createPreviewPopover( preview, type ) {
        const popover = document.createElement( 'div' );
        popover.className = 'preview-popover';

        const header = document.createElement( 'div' );
        header.className = 'preview-popover-header';

        const title = document.createElement( 'h4' );
        title.textContent = type === 'code' ? '💻 Code Preview' : '📝 Code Explanation';
        header.appendChild( title );

        const closeBtn = document.createElement( 'button' );
        closeBtn.className = 'preview-popover-close';
        closeBtn.textContent = '×';
        closeBtn.onclick = () => this.closePreviewPopover();
        header.appendChild( closeBtn );

        popover.appendChild( header );

        const body = document.createElement( 'div' );
        body.className = 'preview-popover-body';

        if ( type === 'code' ) {
            // Show code preview
            if ( preview.code_preview && preview.code_preview.trim() ) {
                const label = document.createElement( 'span' );
                label.className = 'preview-popover-label';
                label.textContent = 'Executable Code';
                body.appendChild( label );

                const codeBlock = document.createElement( 'div' );
                codeBlock.className = 'preview-popover-code';
                codeBlock.textContent = preview.code_preview;
                body.appendChild( codeBlock );
            } else {
                const empty = document.createElement( 'div' );
                empty.className = 'preview-popover-empty';
                empty.textContent = 'No code available for this snapshot';
                body.appendChild( empty );
            }
        } else {
            // Show solution summary gist
            if ( preview.solution_summary_gist && preview.solution_summary_gist.trim() ) {
                const label = document.createElement( 'span' );
                label.className = 'preview-popover-label';
                label.textContent = 'What the code does';
                body.appendChild( label );

                const gistBlock = document.createElement( 'div' );
                gistBlock.className = 'preview-popover-gist';
                gistBlock.textContent = preview.solution_summary_gist;
                body.appendChild( gistBlock );
            } else {
                const empty = document.createElement( 'div' );
                empty.className = 'preview-popover-empty';
                empty.textContent = 'No explanation available for this snapshot';
                body.appendChild( empty );
            }
        }

        popover.appendChild( body );
        return popover;
    }

    /**
     * Position popover near the anchor element.
     */
    positionPopover( popover, anchorElement ) {
        const rect = anchorElement.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Initial position below the anchor
        let top = rect.bottom + 8;
        let left = rect.left;

        // Add to DOM temporarily to get dimensions
        popover.style.visibility = 'hidden';
        document.body.appendChild( popover );
        const popoverRect = popover.getBoundingClientRect();
        document.body.removeChild( popover );
        popover.style.visibility = 'visible';

        // Adjust if would go off right edge
        if ( left + popoverRect.width > viewportWidth - 20 ) {
            left = viewportWidth - popoverRect.width - 20;
        }

        // Adjust if would go off left edge
        if ( left < 20 ) {
            left = 20;
        }

        // Adjust if would go off bottom edge - show above instead
        if ( top + popoverRect.height > viewportHeight - 20 ) {
            top = rect.top - popoverRect.height - 8;
        }

        // Ensure not off top
        if ( top < 20 ) {
            top = 20;
        }

        popover.style.top = `${top}px`;
        popover.style.left = `${left}px`;
    }

    /**
     * Close and cleanup preview popover.
     */
    closePreviewPopover() {
        if ( this._currentPopover ) {
            this._currentPopover.remove();
            this._currentPopover = null;
        }
        if ( this._currentPopoverOverlay ) {
            this._currentPopoverOverlay.remove();
            this._currentPopoverOverlay = null;
        }
        if ( this._popoverEscListener ) {
            document.removeEventListener( 'keydown', this._popoverEscListener );
            this._popoverEscListener = null;
        }
    }

    // ============================================================================
    // Similarity Modal (Phase 4: Code Similarity Drill-Down)
    // ============================================================================

    /**
     * Show the similarity modal with snapshots similar to the given one.
     *
     * @param {string} idHash - The source snapshot's ID hash
     */
    async showSimilarSnapshots( idHash ) {
        // Show loading state
        document.getElementById( 'similarity-loading' ).style.display = 'block';
        document.getElementById( 'similarity-content' ).style.display = 'none';
        document.getElementById( 'similarity-error' ).style.display = 'none';

        // Update modal title
        document.getElementById( 'similarity-modal-title' ).textContent =
            `Similar Snapshots for: ${idHash.substring( 0, 8 )}...`;

        // Show modal
        this._attachSimilarityModalEscListener();
        document.getElementById( 'similarity-modal' ).style.display = 'flex';

        try {
            // Fetch similar snapshots from API
            const response = await this.apiCall( `/admin/snapshots/${idHash}/similar` );

            // Update modal title with source question
            if ( response.source_snapshot ) {
                const truncatedSource = response.source_snapshot.length > 60
                    ? response.source_snapshot.substring( 0, 60 ) + '...'
                    : response.source_snapshot;
                document.getElementById( 'similarity-modal-title' ).textContent =
                    `Similar Snapshots: "${truncatedSource}"`;
            }

            // Populate code similarity column
            const codeList = document.getElementById( 'code-similar-list' );
            const codeCount = document.getElementById( 'code-similar-count' );
            codeCount.textContent = `Found ${response.total_code_matches} match${response.total_code_matches !== 1 ? 'es' : ''}`;

            if ( response.code_similar.length === 0 ) {
                codeList.innerHTML = '<div class="similarity-empty">No similar code found</div>';
            } else {
                codeList.innerHTML = response.code_similar.map( result =>
                    this.createSimilarResultItem( result, 'code' )
                ).join( '' );
            }

            // Populate explanation similarity column
            const explList = document.getElementById( 'explanation-similar-list' );
            const explCount = document.getElementById( 'explanation-similar-count' );
            explCount.textContent = `Found ${response.total_explanation_matches} match${response.total_explanation_matches !== 1 ? 'es' : ''}`;

            if ( response.explanation_similar.length === 0 ) {
                explList.innerHTML = '<div class="similarity-empty">No similar explanations found</div>';
            } else {
                explList.innerHTML = response.explanation_similar.map( result =>
                    this.createSimilarResultItem( result, 'explanation' )
                ).join( '' );
            }

            // Populate gist similarity column
            const gistList = document.getElementById( 'solution-gist-similar-list' );
            const gistCount = document.getElementById( 'solution-gist-similar-count' );
            gistCount.textContent = `Found ${response.total_solution_gist_matches} match${response.total_solution_gist_matches !== 1 ? 'es' : ''}`;

            if ( response.solution_gist_similar.length === 0 ) {
                gistList.innerHTML = '<div class="similarity-empty">No similar gists found</div>';
            } else {
                gistList.innerHTML = response.solution_gist_similar.map( result =>
                    this.createSimilarResultItem( result, 'gist' )
                ).join( '' );
            }

            // Hide loading, show content
            document.getElementById( 'similarity-loading' ).style.display = 'none';
            document.getElementById( 'similarity-content' ).style.display = 'block';

        } catch ( error ) {
            console.error( 'Failed to fetch similar snapshots:', error );
            document.getElementById( 'similarity-loading' ).style.display = 'none';
            document.getElementById( 'similarity-error' ).textContent =
                `Failed to find similar snapshots: ${error.message}`;
            document.getElementById( 'similarity-error' ).style.display = 'block';
        }
    }

    /**
     * Create HTML for a single similar result item.
     *
     * @param {object} result - The similarity result object
     * @param {string} type - 'code', 'explanation', or 'gist'
     * @returns {string} HTML string
     */
    createSimilarResultItem( result, type ) {
        // Get the similarity score
        const score = result.similarity || 0;
        const scorePercent = score.toFixed( 1 );

        // Determine score class
        let scoreClass = 'low-match';
        if ( score >= 100 ) {
            scoreClass = 'exact-match';
        } else if ( score >= 90 ) {
            scoreClass = 'high-match';
        } else if ( score >= 75 ) {
            scoreClass = 'medium-match';
        }

        // Truncate question preview if needed
        const questionPreview = result.question_preview.length > 80
            ? result.question_preview.substring( 0, 80 ) + '...'
            : result.question_preview;

        // Select content and CSS class based on similarity type
        let contentText = '';
        let contentClass = 'similar-result-gist';
        let maxLength = 150;

        switch ( type ) {
            case 'code':
                contentText = result.code_preview || '';
                contentClass = 'similar-result-code';
                maxLength = 400;  // Show more code
                break;
            case 'explanation':
                contentText = result.solution_summary_preview || '';
                contentClass = 'similar-result-gist';
                maxLength = 200;
                break;
            case 'gist':
            default:
                contentText = result.solution_summary_gist || '';
                contentClass = 'similar-result-gist';
                maxLength = 150;
                break;
        }

        // Truncate display content if needed
        const displayContent = contentText.length > maxLength
            ? contentText.substring( 0, maxLength ) + '...'
            : contentText;

        return `
            <div class="similar-result-item ${scoreClass}" onclick="dashboard.viewDetails('${result.id_hash}'); dashboard.closeSimilarityModal();">
                <div class="similar-result-header">
                    <span class="similar-result-score ${scoreClass}">${scorePercent}%</span>
                    <span class="similar-result-id">${result.id_hash.substring( 0, 8 )}</span>
                </div>
                <div class="similar-result-question">${escapeHtml( questionPreview )}</div>
                ${displayContent ? `<div class="${contentClass}">${escapeHtml( displayContent )}</div>` : ''}
                <div class="similar-result-date">${this.formatDate( result.created_date )}</div>
            </div>
        `;
    }

    /**
     * Close the similarity modal.
     */
    closeSimilarityModal() {
        this._detachSimilarityModalEscListener();
        document.getElementById( 'similarity-modal' ).style.display = 'none';
    }

    /**
     * Attach ESC key listener for similarity modal.
     */
    _attachSimilarityModalEscListener() {
        this.similarityModalEscListener = ( event ) => {
            if ( event.key === 'Escape' ) {
                event.preventDefault();
                event.stopPropagation();
                this.closeSimilarityModal();
            }
        };
        document.addEventListener( 'keydown', this.similarityModalEscListener );
    }

    /**
     * Detach ESC key listener for similarity modal.
     */
    _detachSimilarityModalEscListener() {
        if ( this.similarityModalEscListener ) {
            document.removeEventListener( 'keydown', this.similarityModalEscListener );
            this.similarityModalEscListener = null;
        }
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
