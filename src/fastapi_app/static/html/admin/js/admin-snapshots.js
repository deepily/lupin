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
    }

    async init() {
        // Check authentication
        await this.setupAuthentication();

        // Setup event listeners
        this.setupEventListeners();

        // Display user info
        this.displayUserInfo();
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

            // Populate modal
            document.getElementById( 'detail-question' ).textContent = snapshot.question;
            document.getElementById( 'detail-question-normalized' ).textContent = snapshot.question_normalized;
            document.getElementById( 'detail-question-gist' ).textContent = snapshot.question_gist;
            document.getElementById( 'detail-answer' ).textContent = snapshot.answer || 'No answer';
            document.getElementById( 'detail-answer-conversational' ).textContent = snapshot.answer_conversational || 'No conversational answer';
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
}

// Initialize on page load
let dashboard;
document.addEventListener( 'DOMContentLoaded', () => {
    dashboard = new AdminSnapshotsDashboard();
    dashboard.init();
});
