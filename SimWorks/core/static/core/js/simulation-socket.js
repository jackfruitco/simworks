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

        this.connect();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws/simulation/${this.simulationId}/`;

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            console.log('[SimulationSocket] Connected');
            this.reconnectAttempts = 0;
            this.dispatch('connected', { simulationId: this.simulationId });

            // Send client_ready message
            this.send('client_ready', { content_mode: this.contentMode });
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
