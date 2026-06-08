/*
 * Broadcast panel — user → all CC sessions UI.
 *
 * Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md
 * AC8 (panel + confirm modal) + AC9 (live aggregate) + AC10 (markdown + DOMPurify).
 *
 * Wiring:
 *   - GET /api/commons/active-sessions  → populates the recipient chip-row
 *   - POST /api/commons/broadcast-to-cc-sessions  → confirm-modal Send action
 *   - Live aggregate updated via window.broadcastPanel.handleAck() which the
 *     notifications.js notification_queue_update switch invokes for every
 *     `commons_broadcast_ack` envelope.
 *
 * Sanitization:
 *   - Preview pane: DOMPurify.sanitize( marked.parse( body ) ) → innerHTML  (AC10 / T2)
 *   - Aggregate body_summary: rendered via .textContent — never innerHTML   (AC9 / T10)
 */

( function() {
    "use strict";

    // ─── Endpoints + constants ─────────────────────────────────────────
    const ACTIVE_SESSIONS_URL = "/api/commons/active-sessions";
    const BROADCAST_URL       = "/api/commons/broadcast-to-cc-sessions";
    const AUTO_DISMISS_MS     = 5 * 60 * 1000;   // 5 minutes (matches AC7 ack-tracker TTL)

    // ─── Per-broadcast aggregate state ─────────────────────────────────
    // Cleared (or replaced) when a new broadcast is submitted.
    let recipientCache = [ ];   // Last known active-sessions list
    let activeAggregate = null;  /* {
        broadcastId      : string,
        expectedSessions : Set<string>,
        receivedAcks     : Map<sessionId, {persona_name, persona_icon, persona_color, status, body_summary}>,
        dismissTimer     : number | null,
        timedOut         : boolean,
    } */

    // ─── Auth ──────────────────────────────────────────────────────────
    function getAccessToken() {
        return localStorage.getItem( "lupin_access_token" ) || "";
    }

    function authHeaders( extra ) {
        const headers = { "Authorization": "Bearer " + getAccessToken() };
        if ( extra ) Object.assign( headers, extra );
        return headers;
    }

    // ─── Recipient chip-row ────────────────────────────────────────────
    async function fetchActiveSessions() {
        const row = document.getElementById( "broadcast-recipients-row" );
        if ( !row ) return;
        renderChips( null );   // show "loading..." state
        try {
            const res = await fetch( ACTIVE_SESSIONS_URL, { headers: authHeaders() } );
            if ( !res.ok ) throw new Error( "HTTP " + res.status );
            const data = await res.json();
            recipientCache = Array.isArray( data.sessions ) ? data.sessions : [ ];
            renderChips( recipientCache );
        } catch ( e ) {
            recipientCache = [ ];
            renderChips( [ ], "failed to load: " + e.message );
        }
        updateSendButton();
    }

    function renderChips( sessions, errorMsg ) {
        const row = document.getElementById( "broadcast-recipients-row" );
        if ( !row ) return;

        // Preserve the static label + refresh button while replacing the chip set.
        const label   = row.querySelector( "#broadcast-recipients-label" );
        const refresh = row.querySelector( "#broadcast-recipients-refresh" );
        row.innerHTML = "";
        if ( label   ) row.appendChild( label );

        // @all text-injector chip leads the row whenever recipients are showable
        // (loading / sessions). It just inserts the literal `@all ` token; the
        // broadcast handler's `_parse_body` already treats `@all` as default scope.
        const showAllInjector = sessions === null || ( !errorMsg && sessions && sessions.length > 0 );
        if ( showAllInjector ) {
            row.appendChild( buildAtAllChip() );
        }

        if ( sessions === null ) {
            const loading = document.createElement( "span" );
            loading.className   = "broadcast-chip";
            loading.textContent = "loading…";
            row.appendChild( loading );
        } else if ( errorMsg ) {
            const err = document.createElement( "span" );
            err.className   = "broadcast-chip no-recipients";
            err.textContent = errorMsg;
            row.appendChild( err );
        } else if ( sessions.length === 0 ) {
            const empty = document.createElement( "span" );
            empty.className   = "broadcast-chip no-recipients";
            empty.textContent = "no active sessions";
            row.appendChild( empty );
        } else {
            sessions.forEach( s => row.appendChild( buildChip( s ) ) );
        }

        if ( refresh ) row.appendChild( refresh );
    }

    // Insert `@<persona> ` text into the broadcast textarea at the current
    // cursor position, then refocus. Trailing space matches natural typing
    // flow; no colon so the handler's default-scope fallback (line 64 of
    // broadcast_handler.py) lets every session see the line ("carpet bomb"
    // semantics ratified 2026-05-17).
    function injectMentionAtCursor( token ) {
        const ta = document.getElementById( "broadcast-textarea" );
        if ( !ta ) return;
        const insertText = "@" + token + " ";
        const start = ta.selectionStart;
        const end   = ta.selectionEnd;
        const before = ta.value.slice( 0, start );
        const after  = ta.value.slice( end );
        ta.value = before + insertText + after;
        const newPos = start + insertText.length;
        ta.setSelectionRange( newPos, newPos );
        ta.focus();
        // Fire input event so preview + send-button state update via the existing wiring.
        ta.dispatchEvent( new Event( "input", { bubbles: true } ) );
    }

    function buildAtAllChip() {
        const chip = document.createElement( "button" );
        chip.type      = "button";
        chip.className = "broadcast-chip broadcast-chip-all";
        chip.title     = "Insert @all into the message";
        const icon = document.createElement( "span" );
        icon.className   = "broadcast-chip-icon";
        icon.textContent = "📣";
        const name = document.createElement( "span" );
        name.textContent = "@all";
        chip.appendChild( icon );
        chip.appendChild( name );
        chip.addEventListener( "click", () => injectMentionAtCursor( "all" ) );
        return chip;
    }

    function buildChip( session, clickable ) {
        const personaName = session.persona_name || session.session_id || "session";
        const isClickable = clickable !== false;
        const chip = document.createElement( isClickable ? "button" : "span" );
        if ( isClickable ) chip.type = "button";
        chip.className = "broadcast-chip";
        if ( isClickable ) chip.title = "Insert @" + personaName + " into the message";
        if ( session.persona_color ) {
            chip.style.borderColor = session.persona_color;
        }
        const icon = document.createElement( "span" );
        icon.className   = "broadcast-chip-icon";
        icon.textContent = session.persona_icon || "👤";
        const name = document.createElement( "span" );
        name.textContent = personaName;
        chip.appendChild( icon );
        chip.appendChild( name );
        if ( isClickable ) {
            chip.addEventListener( "click", () => injectMentionAtCursor( personaName ) );
        }
        return chip;
    }

    // ─── Textarea / preview / send-button state ────────────────────────
    function updatePreview() {
        const ta      = document.getElementById( "broadcast-textarea" );
        const preview = document.getElementById( "broadcast-preview" );
        if ( !ta || !preview ) return;
        const raw = ta.value;
        if ( !raw.trim() ) {
            preview.classList.add( "empty" );
            preview.textContent = "preview appears here…";
            return;
        }
        preview.classList.remove( "empty" );
        // AC10 + T2: marked.parse() output MUST pass through DOMPurify before innerHTML.
        const html = sanitizeMarkdown( raw );
        preview.innerHTML = html;
    }

    function sanitizeMarkdown( raw ) {
        if ( typeof marked === "undefined" || typeof DOMPurify === "undefined" ) {
            // Bare-text fallback if either vendor lib failed to load — never let raw HTML reach the DOM.
            const div = document.createElement( "div" );
            div.textContent = raw;
            return div.innerHTML;
        }
        return DOMPurify.sanitize( marked.parse( raw ) );
    }

    function updateSendButton() {
        const ta  = document.getElementById( "broadcast-textarea" );
        const btn = document.getElementById( "broadcast-send-button" );
        if ( !ta || !btn ) return;
        const hasBody       = ta.value.trim().length > 0;
        const hasRecipients = recipientCache.length > 0;
        btn.disabled = !( hasBody && hasRecipients );
        btn.title    = btn.disabled
            ? ( !hasBody ? "type a message first" : "no active sessions to broadcast to" )
            : "send broadcast to all listed sessions";
    }

    // ─── Confirm modal ─────────────────────────────────────────────────
    function showConfirmModal() {
        const ta = document.getElementById( "broadcast-textarea" );
        if ( !ta || !ta.value.trim() ) return;
        if ( recipientCache.length === 0 )       return;

        const overlay = document.createElement( "div" );
        overlay.id = "broadcast-confirm-modal-overlay";

        const modal = document.createElement( "div" );
        modal.id = "broadcast-confirm-modal";

        const heading = document.createElement( "h4" );
        heading.textContent = "Send broadcast to " + recipientCache.length +
            " session" + ( recipientCache.length === 1 ? "" : "s" ) + "?";
        modal.appendChild( heading );

        const recipientsDiv = document.createElement( "div" );
        recipientsDiv.className = "modal-recipients";
        recipientCache.forEach( s => recipientsDiv.appendChild( buildChip( s, false ) ) );
        modal.appendChild( recipientsDiv );

        const previewDiv = document.createElement( "div" );
        previewDiv.className = "modal-preview";
        previewDiv.innerHTML = sanitizeMarkdown( ta.value );   // AC10 + T2
        modal.appendChild( previewDiv );

        const buttonsDiv = document.createElement( "div" );
        buttonsDiv.className = "modal-buttons";

        const cancelBtn = document.createElement( "button" );
        cancelBtn.className   = "btn-cancel";
        cancelBtn.textContent = "Cancel";
        cancelBtn.addEventListener( "click", () => overlay.remove() );

        const confirmBtn = document.createElement( "button" );
        confirmBtn.className   = "btn-confirm";
        confirmBtn.textContent = "Confirm + Send";
        confirmBtn.addEventListener( "click", async () => {
            confirmBtn.disabled = true;
            confirmBtn.textContent = "sending…";
            try {
                await postBroadcast( ta.value );
                overlay.remove();
            } catch ( e ) {
                confirmBtn.disabled = false;
                confirmBtn.textContent = "Confirm + Send";
                setStatus( "send failed: " + e.message, true );
            }
        } );

        buttonsDiv.appendChild( cancelBtn );
        buttonsDiv.appendChild( confirmBtn );
        modal.appendChild( buttonsDiv );

        overlay.appendChild( modal );
        document.body.appendChild( overlay );

        overlay.addEventListener( "click", ( e ) => {
            if ( e.target === overlay ) overlay.remove();
        } );
    }

    // ─── POST broadcast ────────────────────────────────────────────────
    async function postBroadcast( message ) {
        setStatus( "submitting…" );
        const res = await fetch( BROADCAST_URL, {
            method  : "POST",
            headers : authHeaders( { "Content-Type": "application/json" } ),
            body    : JSON.stringify( {
                message            : message,
                require_ack        : true,
                include_originator : true,
            } ),
        } );

        if ( res.status === 429 ) {
            const retryAfter = res.headers.get( "Retry-After" );
            throw new Error( "rate limited — try again in " +
                ( retryAfter ? retryAfter + "s" : "a moment" ) );
        }
        if ( !res.ok ) {
            const errText = await safeJsonDetail( res );
            throw new Error( "HTTP " + res.status + " " + errText );
        }

        const data = await res.json();
        // Initialize the aggregate panel — start tracking expected sessions.
        const expected = recipientCache.map( s => s.session_id );
        initializeAggregate( data.broadcast_id, expected, data.recipients );

        const ta = document.getElementById( "broadcast-textarea" );
        if ( ta ) ta.value = "";
        updatePreview();
        updateSendButton();

        setStatus( "sent to " + data.recipients + " session" +
            ( data.recipients === 1 ? "" : "s" ) +
            " (broadcast_id " + data.broadcast_id.slice( 0, 8 ) + "…)" );
    }

    async function safeJsonDetail( res ) {
        try {
            const data = await res.json();
            return data.detail || JSON.stringify( data );
        } catch ( _ ) {
            return res.statusText || "";
        }
    }

    function setStatus( msg, isError ) {
        const el = document.getElementById( "broadcast-submit-status" );
        if ( !el ) return;
        el.textContent = msg;
        el.style.color = isError ? "#c92a2a" : "#666";
    }

    // ─── Live aggregate (AC9) ──────────────────────────────────────────
    function initializeAggregate( broadcastId, expectedSessionIds, expectedTotal ) {
        // Replace any prior in-flight aggregate with the new one.
        if ( activeAggregate && activeAggregate.dismissTimer ) {
            clearTimeout( activeAggregate.dismissTimer );
        }
        activeAggregate = {
            broadcastId      : broadcastId,
            expectedSessions : new Set( expectedSessionIds ),
            expectedTotal    : expectedTotal,
            receivedAcks     : new Map(),
            dismissTimer     : null,
            timedOut         : false,
        };
        renderAggregate();
    }

    /**
     * Public hook invoked by notifications.js for every notification with
     * type === "commons_broadcast_ack". The notification.payload shape is:
     *   { broadcast_id, session_id, persona_name, persona_icon, persona_color,
     *     status, body_summary }
     */
    function handleAck( notification ) {
        const payload = notification && notification.payload;
        if ( !payload || !payload.broadcast_id ) return;
        if ( !activeAggregate || activeAggregate.broadcastId !== payload.broadcast_id ) {
            // Aggregate is for a different broadcast (or none) — ignore.
            return;
        }

        activeAggregate.receivedAcks.set( payload.session_id, {
            persona_name  : payload.persona_name,
            persona_icon  : payload.persona_icon,
            persona_color : payload.persona_color,
            status        : payload.status,
            body_summary  : payload.body_summary || "",
        } );

        renderAggregate();
        scheduleAutoDismiss();
    }

    function scheduleAutoDismiss() {
        if ( !activeAggregate ) return;
        if ( activeAggregate.dismissTimer ) {
            clearTimeout( activeAggregate.dismissTimer );
        }
        activeAggregate.dismissTimer = setTimeout( () => {
            if ( !activeAggregate ) return;
            const received = activeAggregate.receivedAcks.size;
            const expected = activeAggregate.expectedSessions.size;
            if ( received < expected ) {
                activeAggregate.timedOut = true;
                renderAggregate();
            } else {
                // Fully acked — quietly dismiss
                dismissAggregate();
            }
        }, AUTO_DISMISS_MS );
    }

    function dismissAggregate() {
        const panel = document.getElementById( "broadcast-aggregate-panel" );
        if ( panel ) panel.innerHTML = "";
        activeAggregate = null;
    }

    function renderAggregate() {
        const panel = document.getElementById( "broadcast-aggregate-panel" );
        if ( !panel ) return;
        panel.innerHTML = "";

        if ( !activeAggregate ) return;

        const received = activeAggregate.receivedAcks.size;
        const expected = activeAggregate.expectedSessions.size;
        const summary  = document.createElement( "div" );
        summary.id          = "broadcast-aggregate-summary";

        if ( activeAggregate.timedOut ) {
            panel.classList.add( "timed-out" );
            summary.textContent = received + "/" + expected +
                " sessions acknowledged — " + ( expected - received ) + " timed out";
        } else {
            panel.classList.remove( "timed-out" );
            if ( received === expected ) {
                summary.textContent = "✅ All " + expected + " session" +
                    ( expected === 1 ? "" : "s" ) + " acknowledged";
            } else {
                summary.textContent = received + "/" + expected + " complete";
            }
        }
        panel.appendChild( summary );

        // Render received acks (text-content for body_summary per T10)
        for ( const [ sid, ack ] of activeAggregate.receivedAcks ) {
            const row = document.createElement( "div" );
            row.className = "broadcast-ack-row";

            const icon = document.createElement( "span" );
            icon.className   = "broadcast-ack-icon";
            icon.textContent = ack.persona_icon || "👤";

            const persona = document.createElement( "span" );
            persona.className   = "broadcast-ack-persona";
            persona.textContent = ack.persona_name || sid.slice( 0, 8 );

            const status = document.createElement( "span" );
            status.className   = "broadcast-ack-status";
            status.textContent = "[" + ( ack.status || "?" ) + "]";

            const summaryEl = document.createElement( "span" );
            summaryEl.className   = "broadcast-ack-summary";
            // T10: body_summary is server-side text — render via textContent, NEVER innerHTML.
            summaryEl.textContent = ack.body_summary;

            row.appendChild( icon );
            row.appendChild( persona );
            row.appendChild( status );
            row.appendChild( summaryEl );
            panel.appendChild( row );
        }

        // Render pending sessions by name when partial
        if ( !activeAggregate.timedOut && received < expected ) {
            const pending = [ ];
            for ( const sid of activeAggregate.expectedSessions ) {
                if ( !activeAggregate.receivedAcks.has( sid ) ) {
                    const cached = recipientCache.find( s => s.session_id === sid );
                    pending.push( cached ? ( cached.persona_name || sid.slice( 0, 8 ) ) : sid.slice( 0, 8 ) );
                }
            }
            if ( pending.length ) {
                const row = document.createElement( "div" );
                row.className   = "broadcast-pending-row";
                row.textContent = "waiting on: " + pending.join( ", " );
                panel.appendChild( row );
            }
        }
    }

    // ─── DOM wiring ────────────────────────────────────────────────────
    function wirePanel() {
        const ta      = document.getElementById( "broadcast-textarea" );
        const btn     = document.getElementById( "broadcast-send-button" );
        const refresh = document.getElementById( "broadcast-recipients-refresh" );

        if ( ta ) {
            ta.addEventListener( "input", () => {
                updatePreview();
                updateSendButton();
            } );
        }
        if ( btn ) {
            btn.addEventListener( "click", () => {
                if ( !btn.disabled ) showConfirmModal();
            } );
        }
        if ( refresh ) {
            refresh.addEventListener( "click", () => fetchActiveSessions() );
        }

        updatePreview();
        updateSendButton();
        fetchActiveSessions();
    }

    if ( document.readyState === "loading" ) {
        document.addEventListener( "DOMContentLoaded", wirePanel );
    } else {
        wirePanel();
    }

    // ─── Public API for notifications.js ───────────────────────────────
    window.broadcastPanel = {
        handleAck         : handleAck,
        refreshSessions   : fetchActiveSessions,
        // Test hooks — used by Playwright E2E to seed state without HTTP.
        _initializeAggregate : initializeAggregate,
        _renderAggregate     : renderAggregate,
    };
} )();
