/**
 * Proxy Trust Dashboard JavaScript
 *
 * Handles trust state visualization, category cards, and recent decision history.
 */

// ============================================================================
// State Management
// ============================================================================

let trustStates       = [];
let recentDecisions   = [];
let selectedCategory  = "";
let currentPage       = 1;
let pageLimit         = 50;
let userEmail         = "";

// SWE category definitions (6 categories)
const SWE_CATEGORIES = [
    { key: "deployment",   icon: "\uD83D\uDE80", label: "Deployment" },
    { key: "testing",      icon: "\uD83E\uDDEA", label: "Testing" },
    { key: "deps",         icon: "\uD83D\uDCE6", label: "Dependencies" },
    { key: "architecture", icon: "\uD83D\uDCD0", label: "Architecture" },
    { key: "destructive",  icon: "\u26A0\uFE0F", label: "Destructive" },
    { key: "general",      icon: "\u2699\uFE0F", label: "General" }
];

const TRUST_LABELS = {
    1 : "Shadow",
    2 : "Provisional",
    3 : "Trusted",
    4 : "Autonomous",
    5 : "Full Trust"
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
        await loadTrustStates();
        await loadRecentDecisions( "" );
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
 * Load trust states from API.
 */
async function loadTrustStates() {
    try {
        showLoading( "loading" );
        document.getElementById( "main-content" ).style.display = "none";

        const response = await apiCall(
            `/proxy/trust/${encodeURIComponent( userEmail )}?domain=swe`, "GET"
        );

        trustStates = response.trust_states || [];

        renderModeBar();
        renderTrustCards( trustStates );

        hideLoading( "loading" );
        document.getElementById( "main-content" ).style.display = "block";

    } catch ( error ) {
        hideLoading( "loading" );
        document.getElementById( "main-content" ).style.display = "block";

        // On 404 or empty, render default cards
        if ( error.message && error.message.includes( "404" ) ) {
            trustStates = [];
            renderModeBar();
            renderTrustCards( [] );
        } else {
            showError( "error-message", "Failed to load trust data: " + error.message );
        }
        console.error( "Load trust states error:", error );
    }
}

/**
 * Load recent decisions for a category (or all).
 */
async function loadRecentDecisions( category ) {
    try {
        let decisions = [];

        if ( category ) {
            // Single category
            const response = await apiCall(
                `/proxy/decisions/swe/${encodeURIComponent( category )}?limit=${pageLimit}`, "GET"
            );
            decisions = response.decisions || [];
        } else {
            // All categories — fetch each and merge
            const allPromises = SWE_CATEGORIES.map( cat =>
                apiCall( `/proxy/decisions/swe/${cat.key}?limit=10`, "GET" )
                    .then( r => r.decisions || [] )
                    .catch( () => [] )
            );
            const allResults = await Promise.all( allPromises );
            decisions = allResults.flat();

            // Sort by created_at descending (newest first)
            decisions.sort( ( a, b ) => {
                const ta = a.created_at ? new Date( a.created_at ).getTime() : 0;
                const tb = b.created_at ? new Date( b.created_at ).getTime() : 0;
                return tb - ta;
            });

            // Limit to pageLimit
            decisions = decisions.slice( 0, pageLimit );
        }

        recentDecisions = decisions;
        currentPage = 1;
        renderRecentDecisions( decisions );

    } catch ( error ) {
        // Show empty state on error
        recentDecisions = [];
        renderRecentDecisions( [] );
        console.error( "Load recent decisions error:", error );
    }
}

// ============================================================================
// UI Rendering
// ============================================================================

/**
 * Render the mode bar — fetch effective mode from API and set dropdown.
 */
async function renderModeBar() {
    document.getElementById( "mode-user" ).textContent = userEmail || "—";
    document.getElementById( "mode-domain" ).textContent = "swe";

    // Fetch current mode from GET /api/proxy/mode
    try {
        const modeData = await apiCall( "/proxy/mode", "GET" );
        const effective     = modeData.effective || "shadow";
        const hasRunningJob = modeData.has_running_job || false;

        // Set dropdown to effective mode
        const select = document.getElementById( "mode-trust-select" );
        select.value = effective;

        // Update status dot
        updateModeStatusDot( hasRunningJob );

    } catch ( error ) {
        console.warn( "Could not fetch trust mode, using default:", error );
        // Leave dropdown at default (shadow)
        updateModeStatusDot( false );
    }
}

/**
 * Update the mode status dot indicator.
 */
function updateModeStatusDot( hasRunningJob ) {
    const dot = document.getElementById( "mode-status-dot" );
    if ( !dot ) return;

    dot.className = "mode-status-dot";

    if ( hasRunningJob ) {
        dot.classList.add( "status-running" );
        dot.title = "Running job — mode change takes effect immediately";
    } else {
        dot.classList.add( "status-idle" );
        dot.title = "No running job — mode change applies to next job";
    }
}

/**
 * Handle trust mode dropdown change.
 */
async function onModeChange( event ) {
    const newMode  = event.target.value;
    const dot      = document.getElementById( "mode-status-dot" );

    try {
        const resp = await apiCall( "/proxy/mode", "PUT", { mode: newMode, domain: "swe" } );

        if ( resp.status === "updated" ) {
            showSuccess( "success-message", `Trust mode changed to ${newMode.toUpperCase()} (active job updated)` );
            if ( dot ) {
                dot.className = "mode-status-dot status-running";
                dot.title = "Running job updated to " + newMode.toUpperCase();
            }
        } else {
            showSuccess( "success-message", `Trust mode queued: ${newMode.toUpperCase()} (applies to next job)` );
            if ( dot ) {
                dot.className = "mode-status-dot status-queued";
                dot.title = "Queued for next job: " + newMode.toUpperCase();
            }
        }

        // Clear message after 4 seconds
        setTimeout( () => {
            const el = document.getElementById( "success-message" );
            if ( el ) { el.style.display = "none"; el.textContent = ""; }
        }, 4000 );

    } catch ( err ) {
        showError( "error-message", "Mode change failed: " + err.message );
        console.error( "Mode change error:", err );
    }
}

/**
 * Render trust cards grid (one card per SWE category).
 */
function renderTrustCards( states ) {
    const grid = document.getElementById( "trust-cards-grid" );
    grid.innerHTML = "";

    SWE_CATEGORIES.forEach( cat => {
        const state = states.find( s => s.category === cat.key );
        const card  = createTrustCard( cat, state );
        grid.appendChild( card );
    });
}

/**
 * Create a single trust card element.
 */
function createTrustCard( cat, state ) {
    const level         = state ? ( state.trust_level || 1 ) : 1;
    const total         = state ? ( state.total_decisions || 0 ) : 0;
    const successful    = state ? ( state.successful_decisions || 0 ) : 0;
    const rejected      = state ? ( state.rejected_decisions || 0 ) : 0;
    const successRate   = total > 0 ? Math.round( ( successful / total ) * 100 ) : null;
    const cbState       = state && state.circuit_breaker_state ? state.circuit_breaker_state : { status: "closed" };
    const cbStatus      = ( cbState.status || "closed" ).toLowerCase();

    const card = document.createElement( "div" );
    card.className = `trust-card trust-card-level-${level}`;

    const rateClass = successRate != null
        ? ( successRate > 80 ? "rate-high" : successRate >= 50 ? "rate-medium" : "rate-low" )
        : "";

    const cbClass = cbStatus === "closed" ? "cb-ok"
                  : cbStatus === "tripped" || cbStatus === "open" ? "cb-tripped"
                  : "cb-cooldown";

    const cbLabel = cbStatus === "closed" ? "OK"
                  : cbStatus === "tripped" || cbStatus === "open" ? "TRIPPED"
                  : "COOLDOWN";

    const rateDisplay = successRate != null
        ? `<div class="success-rate-container">
               <div class="success-rate-label">
                   <span>Success Rate</span>
                   <span>${successRate}%</span>
               </div>
               <div class="success-rate-bar">
                   <div class="success-rate-fill ${rateClass}" style="width: ${successRate}%"></div>
               </div>
           </div>`
        : `<div class="success-rate-container">
               <span class="no-data">No data</span>
           </div>`;

    card.innerHTML = `
        <div class="trust-card-header">
            <span class="category-name">${cat.icon} ${escapeHtml( cat.label )}</span>
        </div>
        <div class="trust-level trust-level-L${level}">L${level}</div>
        <div class="trust-label">${escapeHtml( TRUST_LABELS[ level ] || "Unknown" )}</div>
        ${rateDisplay}
        <div class="trust-card-stats">
            <div class="stat-item">
                <div class="stat-value">${total}</div>
                <div class="stat-label">Total</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${rejected}</div>
                <div class="stat-label">Rejected</div>
            </div>
            <div class="stat-item">
                <span class="cb-status ${cbClass}"><span class="cb-dot"></span> ${cbLabel}</span>
            </div>
        </div>
    `;

    return card;
}

/**
 * Render recent decisions table.
 */
function renderRecentDecisions( decisions ) {
    const tbody     = document.getElementById( "decisions-tbody" );
    const container = document.getElementById( "decisions-table-container" );
    const empty     = document.getElementById( "decisions-empty" );

    tbody.innerHTML = "";

    if ( decisions.length === 0 ) {
        container.style.display = "none";
        empty.style.display = "block";
        document.getElementById( "pagination-container" ).style.display = "none";
        return;
    }

    container.style.display = "block";
    empty.style.display = "none";

    // Paginate
    const start = ( currentPage - 1 ) * pageLimit;
    const end   = start + pageLimit;
    const page  = decisions.slice( start, end );

    page.forEach( decision => {
        const row = document.createElement( "tr" );

        const confidence = decision.confidence != null ? Math.round( decision.confidence * 100 ) : null;
        const confClass  = confidence != null
            ? ( confidence > 80 ? "confidence-high" : confidence >= 50 ? "confidence-medium" : "confidence-low" )
            : "";
        const confText = confidence != null ? confidence + "%" : "—";

        row.innerHTML = `
            <td>${formatRelativeTime( decision.created_at )}</td>
            <td class="question-text" title="${escapeHtml( decision.question || '' )}">${escapeHtml( truncate( decision.question || '', 60 ) )}</td>
            <td>${getActionBadge( decision.action )}</td>
            <td>${getTrustBadge( decision.trust_level )}</td>
            <td><span class="${confClass}">${confText}</span></td>
            <td>${getRatificationBadge( decision.ratification_state )}</td>
        `;

        tbody.appendChild( row );
    });

    updatePagination( decisions.length );
}

// ============================================================================
// Badges (shared with ratify page pattern)
// ============================================================================

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

function getTrustBadge( level ) {
    const n = level || 1;
    return `<span class="badge-trust-${n}">L${n}</span>`;
}

function getRatificationBadge( state ) {
    const classes = {
        pending      : "badge-pending",
        approved     : "badge-approved",
        rejected     : "badge-rejected",
        not_required : "badge-nr"
    };
    const cls   = classes[ state ] || "badge-nr";
    const label = state === "not_required" ? "N/R" : ( state || "N/R" );
    return `<span class="${cls}">${escapeHtml( label )}</span>`;
}

// ============================================================================
// Pagination
// ============================================================================

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

function previousPage() {
    if ( currentPage > 1 ) {
        currentPage--;
        renderRecentDecisions( recentDecisions );
    }
}

function nextPage() {
    const totalPages = Math.ceil( recentDecisions.length / pageLimit );
    if ( currentPage < totalPages ) {
        currentPage++;
        renderRecentDecisions( recentDecisions );
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

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

function escapeHtml( text ) {
    if ( text == null ) return "";
    const div = document.createElement( "div" );
    div.textContent = String( text );
    return div.innerHTML;
}

function truncate( text, maxLen ) {
    if ( !text ) return "";
    if ( text.length <= maxLen ) return text;
    return text.slice( 0, maxLen ) + "...";
}

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

// Category selector change
document.getElementById( "category-selector" )?.addEventListener( "change", function( e ) {
    selectedCategory = e.target.value;
    loadRecentDecisions( selectedCategory );
});

// Trust mode selector change (Phase 8: hot-reload)
document.getElementById( "mode-trust-select" )?.addEventListener( "change", onModeChange );

console.log( "Decision Proxy — Trust Dashboard Ready" );
