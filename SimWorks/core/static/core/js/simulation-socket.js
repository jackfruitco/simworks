/**
 * SimulationSocket - Minimal WebSocket wrapper for simulation events.
 *
 * Dispatches custom DOM events that can be consumed by Alpine.js components
 * or any other event listener. This provides a clean separation between
 * WebSocket communication and UI rendering.
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
        const type = data.type || 'unknown';

        // Dispatch with sim: prefix for all event types
        this.dispatch(type, data);

        // Debug logging
        console.debug('[SimulationSocket] Event:', type, data);
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
