/**
 * SimulationSocket - Minimal WebSocket wrapper for simulation events.
 *
 * Dispatches custom DOM events that can be consumed by Alpine.js components
 * or any other event listener. This provides a clean separation between
 * WebSocket communication and UI rendering.
 *
 * Supports both legacy format and new standardized envelope format:
 * - Legacy: { type: "chat.message_created", content: "..." }
 * - Envelope: { event_id: "uuid", event_type: "message.created", payload: {...} }
 *
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Event deduplication via seenEventIds
 * - Catch-up API integration for missed events on reconnect
 * - Gap detection for heuristic warning
 *
 * Usage:
 *   const socket = new SimulationSocket(simulationId, options);
 *
 *   // Listen for events in Alpine.js:
 *   <div @sim:chat.message_created.window="handleMessage($event.detail)">
 *
 *   // Or vanilla JS:
 *   window.addEventListener('sim:chat.message_created', (e) => {
 *       console.log(e.detail);
 *   });
 *
 * Events dispatched:
 *   - sim:init_message
 *   - sim:chat.message_created
 *   - sim:typing
 *   - sim:stopped_typing
 *   - sim:simulation.feedback_created
 *   - sim:message_status_update
 *   - sim:simulation.state_changed
 *   - sim:feedback.failed
 *   - sim:feedback.retrying
 *   - sim:simulation.metadata.results_created
 *   - sim:error
 *   - sim:connected
 *   - sim:disconnected
 */
class SimulationSocket {
    constructor(simulationId, options = {}) {
        this.simulationId = simulationId;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 10;
        this.reconnectDelay = options.reconnectDelay || 1000;
        this.contentMode = options.contentMode || 'fullHtml';

        // Track seen event IDs for deduplication (limited to prevent memory leaks)
        this.seenEventIds = new Set();
        this.maxSeenEventIds = options.maxSeenEventIds || 1000;

        // Catch-up tracking
        this.lastSeenEventId = null;
        this.lastSeenCreatedAt = null;
        this.catchupInProgress = false;
        this.storageKey = `simSocket_lastSeen_${simulationId}`;

        // Gap detection threshold (ms) - if event timestamp is older than this, warn
        this.gapThresholdMs = options.gapThresholdMs || 5000;

        // JWT token for catch-up API (optional, will use session auth if not provided)
        this.authToken = options.authToken || null;

        // Restore last seen event from session storage
        this.restoreLastSeen();

        this.connect();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const tokenParam = this.authToken ? `?token=${encodeURIComponent(this.authToken)}` : '';
        const url = `${protocol}//${window.location.host}/ws/simulation/${this.simulationId}/${tokenParam}`;

        this.ws = new WebSocket(url);
        const isReconnect = this.reconnectAttempts > 0;

        this.ws.onopen = () => {
            console.log('[SimulationSocket] Connected');
            const previousAttempts = this.reconnectAttempts;
            this.reconnectAttempts = 0;
            this.dispatch('connected', { simulationId: this.simulationId });

            // Send client_ready message
            this.send('client_ready', { content_mode: this.contentMode });

            // Perform catch-up if reconnecting and we have a last seen event
            if (isReconnect && this.lastSeenEventId) {
                console.log('[SimulationSocket] Reconnected, initiating catch-up from:', this.lastSeenEventId);
                this.performCatchup();
            }
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('[SimulationSocket] Failed to parse message:', e);
            }
        };

        this.ws.onclose = (event) => {
            console.log('[SimulationSocket] Disconnected', event.code, event.reason);
            this.dispatch('disconnected', { code: event.code, reason: event.reason });
            this.reconnect();
        };

        this.ws.onerror = (error) => {
            console.error('[SimulationSocket] Error:', error);
        };
    }

    reconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('[SimulationSocket] Max reconnect attempts reached');
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

        console.log(`[SimulationSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => this.connect(), delay);
    }

    handleMessage(data) {
        // Check if this is the new envelope format (has event_type and event_id)
        const isEnvelope = data.event_type && data.event_id;

        if (isEnvelope) {
            // New envelope format - check for duplicate
            if (this.isDuplicate(data.event_id)) {
                console.debug('[SimulationSocket] Skipping duplicate event:', data.event_id);
                return;
            }

            // Track this event ID
            this.trackEventId(data.event_id);

            // Update last seen for catch-up
            this.updateLastSeen(data.event_id, data.created_at);

            // Gap detection
            this.detectGap(data.created_at);

            // Extract event type and merge payload with envelope metadata
            const type = data.event_type;
            const detail = {
                ...data.payload,
                event_id: data.event_id,
                event_type: data.event_type,
                correlation_id: data.correlation_id,
                created_at: data.created_at,
            };

            // Dispatch with sim: prefix
            this.dispatch(type, detail);

            // Debug logging
            console.debug('[SimulationSocket] Envelope event:', type, detail);
        } else {
            // Legacy format - use type field directly
            const type = data.type || 'unknown';

            // Dispatch with sim: prefix for all event types
            this.dispatch(type, data);

            // Debug logging
            console.debug('[SimulationSocket] Legacy event:', type, data);
        }
    }

    /**
     * Check if an event ID has already been seen (duplicate detection).
     * @param {string} eventId - The event ID to check
     * @returns {boolean} True if this event was already processed
     */
    isDuplicate(eventId) {
        return this.seenEventIds.has(eventId);
    }

    /**
     * Track an event ID for deduplication.
     * Automatically prunes old entries when limit is reached.
     * @param {string} eventId - The event ID to track
     */
    trackEventId(eventId) {
        // Prune oldest entries if we're at the limit
        if (this.seenEventIds.size >= this.maxSeenEventIds) {
            // Convert to array, remove first half, convert back to Set
            const entries = Array.from(this.seenEventIds);
            this.seenEventIds = new Set(entries.slice(entries.length / 2));
        }
        this.seenEventIds.add(eventId);
    }

    /**
     * Update the last seen event ID and timestamp.
     * Persists to sessionStorage for catch-up on reconnect.
     * @param {string} eventId - The event ID
     * @param {string} createdAt - ISO 8601 timestamp
     */
    updateLastSeen(eventId, createdAt) {
        this.lastSeenEventId = eventId;
        this.lastSeenCreatedAt = createdAt;

        // Persist to sessionStorage (survives page refresh within session)
        try {
            sessionStorage.setItem(this.storageKey, JSON.stringify({
                eventId,
                createdAt,
                timestamp: Date.now(),
            }));
        } catch (e) {
            console.warn('[SimulationSocket] Failed to persist lastSeen:', e);
        }
    }

    /**
     * Restore last seen event from sessionStorage.
     */
    restoreLastSeen() {
        try {
            const stored = sessionStorage.getItem(this.storageKey);
            if (stored) {
                const data = JSON.parse(stored);
                // Only restore if data is less than 1 hour old
                const maxAge = 60 * 60 * 1000; // 1 hour
                if (Date.now() - data.timestamp < maxAge) {
                    this.lastSeenEventId = data.eventId;
                    this.lastSeenCreatedAt = data.createdAt;
                    console.debug('[SimulationSocket] Restored lastSeen:', data.eventId);
                } else {
                    // Clean up stale data
                    sessionStorage.removeItem(this.storageKey);
                }
            }
        } catch (e) {
            console.warn('[SimulationSocket] Failed to restore lastSeen:', e);
        }
    }

    /**
     * Detect potential gap in events based on timestamp.
     * Logs a warning if the event appears to be significantly delayed.
     * @param {string} eventCreatedAt - ISO 8601 timestamp of the event
     */
    detectGap(eventCreatedAt) {
        if (!eventCreatedAt) return;

        try {
            const eventTime = new Date(eventCreatedAt).getTime();
            const now = Date.now();
            const age = now - eventTime;

            if (age > this.gapThresholdMs) {
                console.warn(
                    '[SimulationSocket] Potential event gap detected:',
                    `Event is ${Math.round(age / 1000)}s old.`,
                    'Consider catch-up if events were missed.'
                );
            }
        } catch (e) {
            console.warn('[SimulationSocket] Failed to detect gap:', e);
        }
    }

    /**
     * Perform catch-up by fetching missed events from the API.
     * Called automatically on reconnection if lastSeenEventId is set.
     */
    async performCatchup() {
        if (this.catchupInProgress) {
            console.debug('[SimulationSocket] Catch-up already in progress');
            return;
        }

        if (!this.lastSeenEventId) {
            console.debug('[SimulationSocket] No lastSeenEventId, skipping catch-up');
            return;
        }

        this.catchupInProgress = true;
        console.log('[SimulationSocket] Starting catch-up from:', this.lastSeenEventId);

        try {
            let cursor = this.lastSeenEventId;
            let hasMore = true;
            let totalFetched = 0;

            while (hasMore) {
                const response = await this.fetchCatchupEvents(cursor);

                if (!response || !response.items) {
                    console.warn('[SimulationSocket] Invalid catch-up response');
                    break;
                }

                // Process each event
                for (const event of response.items) {
                    // Skip if already seen (deduplication)
                    if (this.isDuplicate(event.event_id)) {
                        continue;
                    }

                    // Replay the event
                    this.handleMessage({
                        event_id: event.event_id,
                        event_type: event.event_type,
                        created_at: event.created_at,
                        correlation_id: event.correlation_id,
                        payload: event.payload,
                    });

                    totalFetched++;
                }

                cursor = response.next_cursor;
                hasMore = response.has_more && cursor;
            }

            console.log(`[SimulationSocket] Catch-up complete: ${totalFetched} events replayed`);

        } catch (e) {
            console.error('[SimulationSocket] Catch-up failed:', e);
        } finally {
            this.catchupInProgress = false;
        }
    }

    /**
     * Fetch catch-up events from the API.
     * @param {string} cursor - Event ID to start after
     * @returns {Promise<{items: Array, next_cursor: string|null, has_more: boolean}>}
     */
    async fetchCatchupEvents(cursor) {
        const url = `/api/v1/simulations/${this.simulationId}/events/?cursor=${encodeURIComponent(cursor)}&limit=50`;

        const headers = {
            'Accept': 'application/json',
        };

        // Add auth header if JWT token provided
        if (this.authToken) {
            headers['Authorization'] = `Bearer ${this.authToken}`;
        }

        const response = await fetch(url, {
            method: 'GET',
            headers,
            credentials: 'include', // Include session cookies
        });

        if (!response.ok) {
            throw new Error(`Catch-up API returned ${response.status}`);
        }

        return response.json();
    }

    dispatch(type, detail) {
        // Dispatch as CustomEvent on window for global listeners
        const event = new CustomEvent(`sim:${type}`, {
            detail,
            bubbles: true,
            cancelable: true
        });
        window.dispatchEvent(event);
    }

    send(type, payload = {}) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, ...payload }));
        } else {
            console.warn('[SimulationSocket] Cannot send - socket not open');
        }
    }

    close() {
        if (this.ws) {
            this.maxReconnectAttempts = 0; // Prevent reconnection
            this.ws.close();
        }
    }

    get isConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    }
}

// Export for module systems and attach to window for global access
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SimulationSocket;
}
window.SimulationSocket = SimulationSocket;
