/**
 * Proxy Ratification Page JavaScript
 *
 * Handles pending decision listing, filtering, ratification, and bulk actions.
 */

// ============================================================================
// State Management
// ============================================================================

let pendingDecisions  = [];
let filteredDecisions = [];
let currentPage       = 1;
let pageLimit         = 25;
let selectedIds       = new Set();
let currentDetailId   = null;
let userEmail         = "";
let currentFilters    = {
    category   : "",
    trustLevel : "",
    action     : ""
};

// ============================================================================
// Initialization
// ============================================================================

requireAuth();

document.addEventListener( "DOMContentLoaded", async function() {
    try {
        const user = await getCurrentUser();
        if ( user && user.email ) {
            userEmail = user.email;
        }
        await loadPending();
    } catch ( error ) {
        hideLoading( "loading" );
        showError( "error-message", "Failed to initialize: " + error.message );
        console.error( "Init error:", error );
    }
});

// ============================================================================
// API Calls
// ============================================================================

/**
 * Load pending decisions from API.
 */
async function loadPending() {
    try {
        showLoading( "loading" );
        document.getElementById( "main-content" ).style.display = "none";

        const response = await apiCall( `/api/proxy/pending/${encodeURIComponent( userEmail )}`, "GET" );

        pendingDecisions = response.decisions || [];
        const summary    = response.summary || {};

        renderSummaryCards( summary );
        applyFilters();

        hideLoading( "loading" );
        document.getElementById( "main-content" ).style.display = "block";

    } catch ( error ) {
        hideLoading( "loading" );
        document.getElementById( "main-content" ).style.display = "block";

        // Show empty state on 404 (no decisions exist yet)
        if ( error.message && error.message.includes( "404" ) ) {
            renderSummaryCards( {} );
            showEmptyState();
        } else {
            showError( "error-message", "Failed to load pending decisions: " + error.message );
        }
        console.error( "Load pending error:", error );
    }
}

/**
 * Ratify a single decision.
 */
async function ratifyDecision( id, approved, feedback ) {
    const params = new URLSearchParams({
        approved   : approved,
        user_email : userEmail
    });
    if ( feedback ) {
        params.append( "feedback", feedback );
    }

    return await apiCall( `/api/proxy/ratify/${id}?${params.toString()}`, "POST" );
}

/**
 * Delete a single pending decision.
 */
async function deleteDecision( id ) {
    const params = new URLSearchParams({ user_email: userEmail });
    return await apiCall( `/api/proxy/decision/${id}?${params.toString()}`, "DELETE" );
}

// ============================================================================
// UI Rendering
// ============================================================================

/**
 * Render summary cards from API summary data.
 */
function renderSummaryCards( summary ) {
    document.getElementById( "stat-pending" ).textContent  = summary.total_pending || 0;
    document.getElementById( "stat-approved" ).textContent = computeApprovedToday();
    document.getElementById( "stat-rejected" ).textContent = computeRejectedToday();

    if ( summary.oldest_pending ) {
        document.getElementById( "stat-oldest" ).textContent = formatRelativeTime( summary.oldest_pending );
    } else {
        document.getElementById( "stat-oldest" ).textContent = "—";
    }
}

/**
 * Compute approved-today count from decisions (client-side).
 */
function computeApprovedToday() {
    const today = new Date().toISOString().slice( 0, 10 );
    return pendingDecisions.filter( d =>
        d.ratification_state === "approved" &&
        d.ratified_at && d.ratified_at.slice( 0, 10 ) === today
    ).length;
}

/**
 * Compute rejected-today count from decisions (client-side).
 */
function computeRejectedToday() {
    const today = new Date().toISOString().slice( 0, 10 );
    return pendingDecisions.filter( d =>
        d.ratification_state === "rejected" &&
        d.ratified_at && d.ratified_at.slice( 0, 10 ) === today
    ).length;
}

/**
 * Render the decisions table with the given list.
 */
function renderTable( decisions ) {
    const tbody = document.getElementById( "decisions-tbody" );
    tbody.innerHTML = "";

    if ( decisions.length === 0 ) {
        document.getElementById( "table-container" ).style.display = "none";
        document.getElementById( "pagination-container" ).style.display = "none";
        showEmptyState();
        return;
    }

    document.getElementById( "table-container" ).style.display = "block";
    document.getElementById( "empty-state" ).style.display = "none";

    // Paginate
    const start = ( currentPage - 1 ) * pageLimit;
    const end   = start + pageLimit;
    const page  = decisions.slice( start, end );

    page.forEach( decision => {
        const row = document.createElement( "tr" );
        row.onclick = ( e ) => {
            if ( e.target.type !== "checkbox" && !e.target.closest( ".action-buttons" ) ) {
                showDecisionDetail( decision.id );
            }
        };

        const isChecked = selectedIds.has( decision.id ) ? "checked" : "";
        const confidence = decision.confidence != null ? Math.round( decision.confidence * 100 ) : null;
        const confClass  = confidence != null
            ? ( confidence > 80 ? "confidence-high" : confidence >= 50 ? "confidence-medium" : "confidence-low" )
            : "";
        const confText = confidence != null ? confidence + "%" : "—";

        row.innerHTML = `
            <td><input type="checkbox" ${isChecked} onclick="event.stopPropagation(); toggleSelect( '${escapeHtml( decision.id )}' )"></td>
            <td><span class="badge badge-shadow">${escapeHtml( decision.category )}</span></td>
            <td class="question-text" title="${escapeHtml( decision.question || '' )}">${escapeHtml( truncate( decision.question || '', 80 ) )}</td>
            <td>${getActionBadge( decision.action )}</td>
            <td>${getTrustBadge( decision.trust_level )}</td>
            <td><span class="${confClass}">${confText}</span></td>
            <td>${formatRelativeTime( decision.created_at )}</td>
            <td class="action-buttons">
                <button class="btn-approve-sm" onclick="event.stopPropagation(); quickApprove( '${escapeHtml( decision.id )}' )" title="Approve">&#10003;</button>
                <button class="btn-reject-sm" onclick="event.stopPropagation(); quickReject( '${escapeHtml( decision.id )}' )" title="Reject">&#10007;</button>
                <button class="btn-delete-sm" onclick="event.stopPropagation(); quickDelete( '${escapeHtml( decision.id )}' )" title="Delete">&#x1F5D1;</button>
            </td>
        `;

        tbody.appendChild( row );
    });

    updatePagination( decisions.length );
}

/**
 * Show the empty state panel.
 */
function showEmptyState() {
    document.getElementById( "empty-state" ).style.display = "block";
    document.getElementById( "table-container" ).style.display = "none";
    document.getElementById( "pagination-container" ).style.display = "none";
}

// ============================================================================
// Badges
// ============================================================================

/**
 * Get HTML for an action badge.
 */
function getActionBadge( action ) {
    const classes = {
        shadow  : "badge-shadow",
        suggest : "badge-suggest",
        act     : "badge-act",
        defer   : "badge-defer"
    };
    const cls = classes[ action ] || "badge-shadow";
    return `<span class="${cls}">${escapeHtml( action || "unknown" )}</span>`;
}

/**
 * Get HTML for a trust level badge.
 */
function getTrustBadge( level ) {
    const n = level || 1;
    return `<span class="badge-trust-${n}">L${n}</span>`;
}

/**
 * Get HTML for a ratification state badge.
 */
function getRatificationBadge( state ) {
    const classes = {
        pending      : "badge-pending",
        approved     : "badge-approved",
        rejected     : "badge-rejected",
        not_required : "badge-nr"
    };
    const cls   = classes[ state ] || "badge-nr";
    const label = state === "not_required" ? "N/R" : ( state || "unknown" );
    return `<span class="${cls}">${escapeHtml( label )}</span>`;
}

// ============================================================================
// Filters
// ============================================================================

/**
 * Apply client-side filters and re-render the table.
 */
function applyFilters() {
    filteredDecisions = pendingDecisions.filter( d => {
        if ( currentFilters.category && d.category !== currentFilters.category ) return false;
        if ( currentFilters.trustLevel && String( d.trust_level ) !== currentFilters.trustLevel ) return false;
        if ( currentFilters.action && d.action !== currentFilters.action ) return false;
        return true;
    });

    currentPage = 1;
    selectedIds.clear();
    updateBulkActions();
    renderTable( filteredDecisions );
}

/**
 * Clear all filters and reload.
 */
function clearFilters() {
    document.getElementById( "filter-category" ).value    = "";
    document.getElementById( "filter-trust-level" ).value = "";
    document.getElementById( "filter-action" ).value      = "";

    currentFilters = { category: "", trustLevel: "", action: "" };
    applyFilters();
}

// Filter event listeners
document.getElementById( "filter-category" )?.addEventListener( "change", function( e ) {
    currentFilters.category = e.target.value;
    applyFilters();
});

document.getElementById( "filter-trust-level" )?.addEventListener( "change", function( e ) {
    currentFilters.trustLevel = e.target.value;
    applyFilters();
});

document.getElementById( "filter-action" )?.addEventListener( "change", function( e ) {
    currentFilters.action = e.target.value;
    applyFilters();
});

// ============================================================================
// Selection & Bulk Actions
// ============================================================================

/**
 * Toggle selection of a single decision.
 */
function toggleSelect( id ) {
    if ( selectedIds.has( id ) ) {
        selectedIds.delete( id );
    } else {
        selectedIds.add( id );
    }
    updateBulkActions();
}

/**
 * Toggle select all visible decisions.
 */
function toggleSelectAll() {
    const selectAll = document.getElementById( "select-all" );
    const start     = ( currentPage - 1 ) * pageLimit;
    const end       = start + pageLimit;
    const page      = filteredDecisions.slice( start, end );

    if ( selectAll.checked ) {
        page.forEach( d => selectedIds.add( d.id ) );
    } else {
        page.forEach( d => selectedIds.delete( d.id ) );
    }

    updateBulkActions();
    renderTable( filteredDecisions );
}

/**
 * Update bulk actions bar visibility and count.
 */
function updateBulkActions() {
    const bar = document.getElementById( "bulk-actions" );
    if ( selectedIds.size > 0 ) {
        bar.style.display = "flex";
        document.getElementById( "selected-count" ).textContent = selectedIds.size + " selected";
    } else {
        bar.style.display = "none";
    }
}

/**
 * Bulk approve all selected decisions.
 */
async function bulkApprove() {
    if ( selectedIds.size === 0 ) return;

    let succeeded = 0;
    let failed    = 0;

    for ( const id of selectedIds ) {
        try {
            await ratifyDecision( id, true, "" );
            succeeded++;
        } catch ( error ) {
            failed++;
            console.error( "Bulk approve failed for", id, error );
        }
    }

    if ( failed > 0 ) {
        showSuccess( "success-message", `Approved ${succeeded} of ${succeeded + failed} decisions. ${failed} failed.` );
    } else {
        showSuccess( "success-message", `Approved ${succeeded} decision${succeeded !== 1 ? "s" : ""} successfully.` );
    }

    selectedIds.clear();
    updateBulkActions();
    await loadPending();
}

/**
 * Generic confirm modal helper.
 *
 * Shows a confirmation dialog with custom title, message, button label,
 * and callback. Reused by bulkReject() and bulkDelete().
 */
let pendingConfirmAction = null;

function showConfirmModal( title, message, confirmLabel, onConfirm ) {
    document.getElementById( "confirm-title" ).textContent   = title;
    document.getElementById( "confirm-message" ).textContent = message;
    const confirmBtn       = document.getElementById( "confirm-yes" );
    confirmBtn.textContent = confirmLabel;
    pendingConfirmAction   = onConfirm;
    confirmBtn.onclick     = function() {
        if ( pendingConfirmAction ) pendingConfirmAction();
        pendingConfirmAction = null;
    };
    document.getElementById( "confirm-modal" ).style.display = "block";
}

/**
 * Close confirm modal and clear pending action.
 */
function closeConfirmModal() {
    document.getElementById( "confirm-modal" ).style.display = "none";
    pendingConfirmAction = null;
}

/**
 * Begin bulk reject — show confirmation dialog.
 */
function bulkReject() {
    if ( selectedIds.size === 0 ) return;

    const count = selectedIds.size;
    showConfirmModal(
        "Confirm Bulk Rejection",
        `Are you sure you want to reject ${count} selected decision${count !== 1 ? "s" : ""}?`,
        "Confirm Reject",
        confirmBulkReject
    );
}

/**
 * Confirm and execute bulk reject.
 */
async function confirmBulkReject() {
    closeConfirmModal();

    let succeeded = 0;
    let failed    = 0;

    for ( const id of selectedIds ) {
        try {
            await ratifyDecision( id, false, "" );
            succeeded++;
        } catch ( error ) {
            failed++;
            console.error( "Bulk reject failed for", id, error );
        }
    }

    if ( failed > 0 ) {
        showSuccess( "success-message", `Rejected ${succeeded} of ${succeeded + failed} decisions. ${failed} failed.` );
    } else {
        showSuccess( "success-message", `Rejected ${succeeded} decision${succeeded !== 1 ? "s" : ""} successfully.` );
    }

    selectedIds.clear();
    updateBulkActions();
    await loadPending();
}

/**
 * Begin bulk delete — show confirmation dialog.
 */
function bulkDelete() {
    if ( selectedIds.size === 0 ) return;

    const count = selectedIds.size;
    showConfirmModal(
        "Confirm Bulk Deletion",
        `Are you sure you want to permanently delete ${count} selected decision${count !== 1 ? "s" : ""}? This cannot be undone.`,
        "Confirm Delete",
        confirmBulkDelete
    );
}

/**
 * Confirm and execute bulk delete.
 */
async function confirmBulkDelete() {
    closeConfirmModal();

    let succeeded = 0;
    let failed    = 0;

    for ( const id of selectedIds ) {
        try {
            await deleteDecision( id );
            succeeded++;
        } catch ( error ) {
            failed++;
            console.error( "Bulk delete failed for", id, error );
        }
    }

    if ( failed > 0 ) {
        showSuccess( "success-message", `Deleted ${succeeded} of ${succeeded + failed} decisions. ${failed} failed.` );
    } else {
        showSuccess( "success-message", `Deleted ${succeeded} decision${succeeded !== 1 ? "s" : ""} successfully.` );
    }

    selectedIds.clear();
    updateBulkActions();
    await loadPending();
}

// ============================================================================
// Quick Actions (inline approve/reject)
// ============================================================================

/**
 * Quick approve a single decision from the table row.
 */
async function quickApprove( id ) {
    try {
        await ratifyDecision( id, true, "" );
        showSuccess( "success-message", "Decision approved." );
        await loadPending();
    } catch ( error ) {
        showError( "error-message", "Approve failed: " + error.message );
    }
}

/**
 * Quick reject a single decision from the table row.
 */
async function quickReject( id ) {
    try {
        await ratifyDecision( id, false, "" );
        showSuccess( "success-message", "Decision rejected." );
        await loadPending();
    } catch ( error ) {
        showError( "error-message", "Reject failed: " + error.message );
    }
}

/**
 * Quick delete a single decision from the table row (with confirmation).
 */
function quickDelete( id ) {
    showConfirmModal(
        "Confirm Deletion",
        "Are you sure you want to permanently delete this decision? This cannot be undone.",
        "Delete",
        async function() {
            closeConfirmModal();
            try {
                await deleteDecision( id );
                showSuccess( "success-message", "Decision deleted." );
                await loadPending();
            } catch ( error ) {
                showError( "error-message", "Delete failed: " + error.message );
            }
        }
    );
}

// ============================================================================
// Decision Detail Modal
// ============================================================================

/**
 * Show detail modal for a specific decision.
 */
function showDecisionDetail( id ) {
    const decision = pendingDecisions.find( d => d.id === id );
    if ( !decision ) return;

    currentDetailId = id;

    const confidence = decision.confidence != null ? Math.round( decision.confidence * 100 ) + "%" : "—";
    const confClass  = decision.confidence != null
        ? ( decision.confidence > 0.8 ? "confidence-high" : decision.confidence >= 0.5 ? "confidence-medium" : "confidence-low" )
        : "";

    const detail = document.getElementById( "decision-detail" );
    detail.innerHTML = `
        <div class="detail-row">
            <span class="detail-label">Category:</span>
            <span class="detail-value"><span class="badge badge-shadow">${escapeHtml( decision.category )}</span></span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Domain:</span>
            <span class="detail-value">${escapeHtml( decision.domain || "swe" )}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Action:</span>
            <span class="detail-value">${getActionBadge( decision.action )}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Trust Level:</span>
            <span class="detail-value">${getTrustBadge( decision.trust_level )}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Confidence:</span>
            <span class="detail-value"><span class="${confClass}">${confidence}</span></span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Sender:</span>
            <span class="detail-value">${escapeHtml( decision.sender_id || "—" )}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Created:</span>
            <span class="detail-value">${decision.created_at ? new Date( decision.created_at ).toLocaleString() : "—"}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Reason:</span>
            <span class="detail-value">${escapeHtml( decision.reason || "—" )}</span>
        </div>

        <div style="margin-top: 16px;">
            <strong>Question:</strong>
            <div class="question-box">${escapeHtml( decision.question || "—" )}</div>
        </div>

        ${decision.decision_value ? `
        <div style="margin-top: 12px;">
            <strong>Decision Value:</strong>
            <div class="question-box">${escapeHtml( decision.decision_value )}</div>
        </div>
        ` : ""}
    `;

    document.getElementById( "feedback-text" ).value = "";
    document.getElementById( "detail-modal" ).style.display = "block";
}

/**
 * Close detail modal.
 */
function closeDetailModal() {
    document.getElementById( "detail-modal" ).style.display = "none";
    currentDetailId = null;
}

/**
 * Approve from the detail modal.
 */
async function modalApprove() {
    if ( !currentDetailId ) return;

    const feedback = document.getElementById( "feedback-text" ).value.trim();

    try {
        await ratifyDecision( currentDetailId, true, feedback );
        closeDetailModal();
        showSuccess( "success-message", "Decision approved." );
        await loadPending();
    } catch ( error ) {
        showError( "error-message", "Approve failed: " + error.message );
    }
}

/**
 * Reject from the detail modal.
 */
async function modalReject() {
    if ( !currentDetailId ) return;

    const feedback = document.getElementById( "feedback-text" ).value.trim();

    try {
        await ratifyDecision( currentDetailId, false, feedback );
        closeDetailModal();
        showSuccess( "success-message", "Decision rejected." );
        await loadPending();
    } catch ( error ) {
        showError( "error-message", "Reject failed: " + error.message );
    }
}

// ============================================================================
// Pagination
// ============================================================================

/**
 * Update pagination controls.
 */
function updatePagination( totalItems ) {
    const container  = document.getElementById( "pagination-container" );
    const totalPages = Math.ceil( totalItems / pageLimit );

    if ( totalPages <= 1 ) {
        container.style.display = "none";
        return;
    }

    container.style.display = "flex";
    document.getElementById( "page-info" ).textContent =
        `Page ${currentPage} of ${totalPages} (${totalItems} decisions)`;

    document.getElementById( "prev-page" ).disabled = currentPage === 1;
    document.getElementById( "next-page" ).disabled = currentPage >= totalPages;
}

/**
 * Go to previous page.
 */
function previousPage() {
    if ( currentPage > 1 ) {
        currentPage--;
        renderTable( filteredDecisions );
    }
}

/**
 * Go to next page.
 */
function nextPage() {
    const totalPages = Math.ceil( filteredDecisions.length / pageLimit );
    if ( currentPage < totalPages ) {
        currentPage++;
        renderTable( filteredDecisions );
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Format an ISO timestamp to relative time ("2h ago", "5m ago").
 */
function formatRelativeTime( isoString ) {
    if ( !isoString ) return "—";

    const date   = new Date( isoString );
    const now    = new Date();
    const diffMs = now - date;

    if ( diffMs < 0 ) return "just now";

    const diffSec  = Math.floor( diffMs / 1000 );
    const diffMin  = Math.floor( diffMs / 60000 );
    const diffHr   = Math.floor( diffMs / 3600000 );
    const diffDays = Math.floor( diffMs / 86400000 );

    if ( diffSec < 60 )  return "just now";
    if ( diffMin < 60 )  return diffMin + "m ago";
    if ( diffHr  < 24 )  return diffHr + "h ago";
    if ( diffDays < 7 )  return diffDays + "d ago";

    return date.toLocaleDateString();
}

/**
 * Escape HTML to prevent XSS.
 */
function escapeHtml( text ) {
    if ( text == null ) return "";
    const div = document.createElement( "div" );
    div.textContent = String( text );
    return div.innerHTML;
}

/**
 * Truncate text to a max length with ellipsis.
 */
function truncate( text, maxLen ) {
    if ( !text ) return "";
    if ( text.length <= maxLen ) return text;
    return text.slice( 0, maxLen ) + "...";
}

// ============================================================================
// Shared UI Helpers (from auth.js pattern)
// ============================================================================

function showElement( id ) {
    const el = document.getElementById( id );
    if ( el ) el.style.display = "block";
}

function hideElement( id ) {
    const el = document.getElementById( id );
    if ( el ) el.style.display = "none";
}

// ============================================================================
// Event Listeners
// ============================================================================

// Close modals on outside click
window.addEventListener( "click", function( event ) {
    if ( event.target.classList.contains( "modal" ) ) {
        event.target.style.display = "none";
        currentDetailId = null;
    }
});

// ============================================================================
// Belt: Focus-triggered refresh (Phase 7)
// ============================================================================

// Re-fetch decisions when tab regains focus (handles notification link clicks)
window.addEventListener( "focus", () => {
    console.log( "[PROXY-RATIFY] Tab focused — refreshing decisions" );
    loadPending();
});

// ============================================================================
// Suspenders: WebSocket real-time updates (Phase 7)
// ============================================================================

/**
 * Connect WebSocket for real-time proxy_decision_new events.
 *
 * Ensures:
 *     - Subscribes to proxy_decision_new event only
 *     - Calls loadPending() on each new decision arrival
 *     - Auto-reconnects on close with 5s delay
 */
function connectProxyWebSocket() {
    const sessionId = "proxy ratify";
    const protocol  = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl     = `${protocol}//${window.location.host}/ws/queue/${sessionId}`;

    const ws = new WebSocket( wsUrl );

    ws.onopen = () => {
        const token = getAccessToken();
        ws.send( JSON.stringify({
            type              : "auth_request",
            token             : token ? `Bearer ${token}` : "",
            session_id        : sessionId,
            subscribed_events : [ "proxy_decision_new" ]
        }));
        console.log( "[PROXY-RATIFY] WebSocket connected, subscribed to proxy_decision_new" );
    };

    ws.onmessage = ( event ) => {
        try {
            const data = JSON.parse( event.data );
            if ( data.type === "proxy_decision_new" ) {
                console.log( "[PROXY-RATIFY] New decision arrived via WebSocket:", data );
                loadPending();
            }
        } catch ( err ) {
            console.warn( "[PROXY-RATIFY] WebSocket message parse error:", err );
        }
    };

    ws.onclose = () => {
        console.log( "[PROXY-RATIFY] WebSocket closed — reconnecting in 5s" );
        setTimeout( connectProxyWebSocket, 5000 );
    };

    ws.onerror = ( err ) => {
        console.warn( "[PROXY-RATIFY] WebSocket error:", err );
    };
}

connectProxyWebSocket();

console.log( "Decision Proxy — Ratification Page Ready" );
