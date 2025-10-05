/**
 * Admin User Management JavaScript
 *
 * Handles user listing, search, filtering, and CRUD operations for admin interface.
 */

// ============================================================================
// State Management
// ============================================================================

let currentPage = 1;
let pageLimit = 50;
let totalUsers = 0;
let currentFilters = {
    search: '',
    role: '',
    status: ''
};
let currentUser = null;
let selectedUserId = null;
let confirmCallback = null;

// ============================================================================
// API Calls
// ============================================================================

/**
 * Load users with pagination and filters
 */
async function loadUsers( page = 1 ) {
    try {
        showLoading( 'loading' );
        hideElement( 'users-table-container' );
        hideElement( 'no-results' );

        currentPage = page;
        const offset = ( page - 1 ) * pageLimit;

        // Build query string
        const params = new URLSearchParams({
            limit: pageLimit,
            offset: offset
        });

        if ( currentFilters.search ) params.append( 'search', currentFilters.search );
        if ( currentFilters.role ) params.append( 'role', currentFilters.role );
        if ( currentFilters.status ) params.append( 'status_filter', currentFilters.status );

        const response = await apiCall( `/admin/users?${params.toString()}`, 'GET' );

        if ( response.users && response.users.length > 0 ) {
            totalUsers = response.total;
            renderUsersTable( response.users );
            updatePagination();
            showElement( 'users-table-container' );
        } else {
            showElement( 'no-results' );
        }

        hideLoading( 'loading' );

    } catch ( error ) {
        hideLoading( 'loading' );
        showError( 'error-message', 'Failed to load users: ' + error.message );
        console.error( 'Load users error:', error );
    }
}

/**
 * Get detailed user information
 */
async function getUserDetails( userId ) {
    try {
        const response = await apiCall( `/admin/users/${userId}`, 'GET' );
        return response;
    } catch ( error ) {
        showError( 'error-message', 'Failed to load user details: ' + error.message );
        throw error;
    }
}

/**
 * Update user roles
 */
async function updateUserRoles( userId, roles ) {
    try {
        const response = await apiCall( `/admin/users/${userId}/roles`, 'PUT', { roles } );
        return response;
    } catch ( error ) {
        showError( 'error-message', 'Failed to update roles: ' + error.message );
        throw error;
    }
}

/**
 * Toggle user status
 */
async function toggleUserStatus( userId, isActive ) {
    try {
        const response = await apiCall( `/admin/users/${userId}/status`, 'PUT', { is_active: isActive } );
        return response;
    } catch ( error ) {
        showError( 'error-message', 'Failed to update status: ' + error.message );
        throw error;
    }
}

/**
 * Admin password reset
 */
async function resetUserPassword( userId, reason = '' ) {
    try {
        const response = await apiCall( `/admin/users/${userId}/reset-password`, 'POST', { reason } );
        return response;
    } catch ( error ) {
        showError( 'error-message', 'Failed to reset password: ' + error.message );
        throw error;
    }
}

// ============================================================================
// UI Rendering
// ============================================================================

/**
 * Render users table
 */
function renderUsersTable( users ) {
    const tbody = document.getElementById( 'users-tbody' );
    tbody.innerHTML = '';

    users.forEach( user => {
        const row = document.createElement( 'tr' );
        row.className = 'user-row';
        row.onclick = () => showUserDetails( user.id );

        row.innerHTML = `
            <td>${escapeHtml( user.email )}</td>
            <td>${getRoleBadges( user.roles )}</td>
            <td>${getStatusBadge( user.is_active )}</td>
            <td>${getVerifiedBadge( user.email_verified )}</td>
            <td>${formatDate( user.created_at )}</td>
            <td>${user.last_login_at ? formatDate( user.last_login_at ) : 'Never'}</td>
            <td>
                <button class="btn-icon" onclick="event.stopPropagation(); showUserDetails( '${user.id}' )" title="View Details">
                    👁️
                </button>
            </td>
        `;

        tbody.appendChild( row );
    });
}

/**
 * Get role badges HTML
 */
function getRoleBadges( roles ) {
    if ( !roles || roles.length === 0 ) return '<span class="badge badge-user">USER</span>';

    return roles.map( role => {
        if ( role === 'admin' ) {
            return '<span class="badge badge-admin">⭐ ADMIN</span>';
        } else {
            return '<span class="badge badge-user">USER</span>';
        }
    }).join( ' ' );
}

/**
 * Get status badge HTML
 */
function getStatusBadge( isActive ) {
    if ( isActive ) {
        return '<span class="badge badge-active">● Active</span>';
    } else {
        return '<span class="badge badge-inactive">● Inactive</span>';
    }
}

/**
 * Get verified badge HTML
 */
function getVerifiedBadge( isVerified ) {
    if ( isVerified ) {
        return '<span class="badge badge-verified">✓ Verified</span>';
    } else {
        return '<span class="text-muted">Not Verified</span>';
    }
}

/**
 * Format date to relative time
 */
function formatDate( isoString ) {
    if ( !isoString ) return 'N/A';

    const date = new Date( isoString );
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor( diffMs / 60000 );
    const diffHours = Math.floor( diffMs / 3600000 );
    const diffDays = Math.floor( diffMs / 86400000 );

    if ( diffMins < 1 ) return 'Just now';
    if ( diffMins < 60 ) return `${diffMins} min ago`;
    if ( diffHours < 24 ) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
    if ( diffDays < 7 ) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;

    return date.toLocaleDateString();
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml( text ) {
    const div = document.createElement( 'div' );
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================================
// User Details Modal
// ============================================================================

/**
 * Show user details modal
 */
async function showUserDetails( userId ) {
    try {
        const user = await getUserDetails( userId );
        currentUser = user;
        selectedUserId = userId;

        const detailsDiv = document.getElementById( 'user-details' );
        detailsDiv.innerHTML = `
            <div class="detail-row">
                <span class="detail-label">Email:</span>
                <span class="detail-value">${escapeHtml( user.email )}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">User ID:</span>
                <span class="detail-value">${escapeHtml( user.id )}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Roles:</span>
                <span class="detail-value">${getRoleBadges( user.roles )}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Verified:</span>
                <span class="detail-value">${getVerifiedBadge( user.email_verified )}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Status:</span>
                <span class="detail-value">${getStatusBadge( user.is_active )}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Created:</span>
                <span class="detail-value">${new Date( user.created_at ).toLocaleString()}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Last Login:</span>
                <span class="detail-value">${user.last_login_at ? new Date( user.last_login_at ).toLocaleString() : 'Never'}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Audit Logs:</span>
                <span class="detail-value">${user.audit_log_count} events</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Failed Logins:</span>
                <span class="detail-value">${user.failed_login_count}</span>
            </div>
        `;

        showElement( 'user-modal' );
    } catch ( error ) {
        console.error( 'Error showing user details:', error );
    }
}

/**
 * Close user details modal
 */
function closeUserModal() {
    hideElement( 'user-modal' );
    currentUser = null;
    selectedUserId = null;
}

// ============================================================================
// Role Editor Modal
// ============================================================================

/**
 * Show role editor modal
 */
function showRoleEditor() {
    if ( !currentUser ) return;

    document.getElementById( 'role-user-email' ).textContent = currentUser.email;

    // Set current roles
    document.getElementById( 'role-admin' ).checked = currentUser.roles.includes( 'admin' );
    document.getElementById( 'role-user' ).checked = currentUser.roles.includes( 'user' );

    hideElement( 'user-modal' );
    showElement( 'role-modal' );
}

/**
 * Close role editor modal
 */
function closeRoleModal() {
    hideElement( 'role-modal' );
    if ( currentUser ) showElement( 'user-modal' );
}

/**
 * Save role changes
 */
async function saveRoles() {
    if ( !selectedUserId ) return;

    const newRoles = [];
    if ( document.getElementById( 'role-admin' ).checked ) newRoles.push( 'admin' );
    if ( document.getElementById( 'role-user' ).checked ) newRoles.push( 'user' );

    if ( newRoles.length === 0 ) {
        showError( 'error-message', 'Please select at least one role' );
        return;
    }

    try {
        await updateUserRoles( selectedUserId, newRoles );
        showSuccess( 'success-message', 'User roles updated successfully' );
        closeRoleModal();
        closeUserModal();
        await loadUsers( currentPage );
    } catch ( error ) {
        console.error( 'Error saving roles:', error );
    }
}

// ============================================================================
// Status Toggle
// ============================================================================

/**
 * Confirm status toggle
 */
function confirmToggleStatus() {
    if ( !currentUser ) return;

    const action = currentUser.is_active ? 'deactivate' : 'activate';
    const message = currentUser.is_active
        ? `Deactivate ${currentUser.email}? They will be logged out immediately.`
        : `Activate ${currentUser.email}? They will be able to log in.`;

    showConfirmDialog( message, async () => {
        try {
            await toggleUserStatus( selectedUserId, !currentUser.is_active );
            const statusText = currentUser.is_active ? 'deactivated' : 'activated';
            showSuccess( 'success-message', `User ${statusText} successfully` );
            closeUserModal();
            await loadUsers( currentPage );
        } catch ( error ) {
            console.error( 'Error toggling status:', error );
        }
    });
}

// ============================================================================
// Password Reset
// ============================================================================

/**
 * Confirm password reset
 */
function confirmResetPassword() {
    if ( !currentUser ) return;

    const message = `Generate new temporary password for ${currentUser.email}? User will be logged out immediately.`;

    showConfirmDialog( message, async () => {
        try {
            const response = await resetUserPassword( selectedUserId, 'Admin password reset' );
            showPasswordModal( response.temporary_password );
            closeUserModal();
        } catch ( error ) {
            console.error( 'Error resetting password:', error );
        }
    });
}

/**
 * Show password result modal
 */
function showPasswordModal( password ) {
    document.getElementById( 'temp-password' ).value = password;
    showElement( 'password-modal' );
}

/**
 * Close password modal
 */
function closePasswordModal() {
    hideElement( 'password-modal' );
    document.getElementById( 'temp-password' ).value = '';
}

/**
 * Copy password to clipboard
 */
function copyPassword() {
    const input = document.getElementById( 'temp-password' );
    input.select();
    document.execCommand( 'copy' );
    showSuccess( 'success-message', 'Password copied to clipboard!' );
}

// ============================================================================
// Confirmation Dialog
// ============================================================================

/**
 * Show confirmation dialog
 */
function showConfirmDialog( message, callback ) {
    document.getElementById( 'confirm-message' ).textContent = message;
    confirmCallback = callback;
    hideElement( 'user-modal' );
    showElement( 'confirm-modal' );
}

/**
 * Confirm action
 */
function confirmYes() {
    if ( confirmCallback ) {
        confirmCallback();
        confirmCallback = null;
    }
    closeConfirmModal();
}

/**
 * Close confirmation modal
 */
function closeConfirmModal() {
    hideElement( 'confirm-modal' );
    if ( currentUser ) showElement( 'user-modal' );
}

// ============================================================================
// Pagination
// ============================================================================

/**
 * Update pagination controls
 */
function updatePagination() {
    const totalPages = Math.ceil( totalUsers / pageLimit );
    document.getElementById( 'page-info' ).textContent = `Page ${currentPage} of ${totalPages} (${totalUsers} users)`;

    // Enable/disable buttons
    document.getElementById( 'prev-page' ).disabled = currentPage === 1;
    document.getElementById( 'next-page' ).disabled = currentPage >= totalPages;
}

/**
 * Go to previous page
 */
function previousPage() {
    if ( currentPage > 1 ) {
        loadUsers( currentPage - 1 );
    }
}

/**
 * Go to next page
 */
function nextPage() {
    const totalPages = Math.ceil( totalUsers / pageLimit );
    if ( currentPage < totalPages ) {
        loadUsers( currentPage + 1 );
    }
}

// ============================================================================
// Search and Filters
// ============================================================================

/**
 * Clear all filters
 */
function clearFilters() {
    document.getElementById( 'user-search' ).value = '';
    document.getElementById( 'role-filter' ).value = '';
    document.getElementById( 'status-filter' ).value = '';

    currentFilters = {
        search: '',
        role: '',
        status: ''
    };

    loadUsers( 1 );
}

/**
 * Debounce function for search
 */
function debounce( func, wait ) {
    let timeout;
    return function executedFunction( ...args ) {
        const later = () => {
            clearTimeout( timeout );
            func( ...args );
        };
        clearTimeout( timeout );
        timeout = setTimeout( later, wait );
    };
}

// ============================================================================
// Utility Functions
// ============================================================================

function showElement( id ) {
    const el = document.getElementById( id );
    if ( el ) el.style.display = 'block';
}

function hideElement( id ) {
    const el = document.getElementById( id );
    if ( el ) el.style.display = 'none';
}

// ============================================================================
// Event Listeners
// ============================================================================

// Search input with debounce
document.getElementById( 'user-search' )?.addEventListener( 'input', debounce( function( e ) {
    currentFilters.search = e.target.value;
    loadUsers( 1 );
}, 300 ));

// Role filter
document.getElementById( 'role-filter' )?.addEventListener( 'change', function( e ) {
    currentFilters.role = e.target.value;
    loadUsers( 1 );
});

// Status filter
document.getElementById( 'status-filter' )?.addEventListener( 'change', function( e ) {
    currentFilters.status = e.target.value;
    loadUsers( 1 );
});

// Close modals on outside click
window.onclick = function( event ) {
    if ( event.target.classList.contains( 'modal' ) ) {
        event.target.style.display = 'none';
    }
};
