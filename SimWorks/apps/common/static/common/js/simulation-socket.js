/**
 * ChatLab SimulationSocket - strict WebSocket wrapper for the v1 ChatLab contract.
 *
 * Outbound client messages always use:
 *   { event_type, correlation_id?, payload }
 *
 * Inbound server events always use:
 *   { event_id, event_type, created_at, correlation_id, payload }
 *
 * Reconnect model:
 * - initial connect => session.hello
 * - reconnect => session.resume with last durable event_id
 * - hard resync => session.resync_required, then the caller must REST bootstrap again
 */

const CHATLAB_WS_PATH = '/ws/v1/chatlab/';
const TRANSIENT_EVENT_TYPES = new Set([
    'session.ready',
    'session.resumed',
    'session.resync_required',
    'error',
    'pong',
    'typing.started',
    'typing.stopped',
]);

class SimulationSocket {
    constructor(simulationId, options = {}) {
        this.simulationId = simulationId;
        this.authToken = options.authToken || null;
        this.accountUuid = options.accountUuid || null;
        this.bootstrapEventId = options.bootstrapEventId || null;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 10;
        this.reconnectDelay = options.reconnectDelay || 1000;
        this.maxSeenEventIds = options.maxSeenEventIds || 1000;
        this.heartbeatIntervalMs = options.heartbeatIntervalMs || 30000;
        this.onResyncRequired = typeof options.onResyncRequired === 'function'
            ? options.onResyncRequired
            : null;

        this.ws = null;
        this.reconnectAttempts = 0;
        this.sessionEstablished = false;
        this.hasConnectedOnce = false;
        this.manuallyClosed = false;
        this.storageKey = `chatlab_last_event_id_${simulationId}`;
        this.lastSeenEventId = this.bootstrapEventId || null;
        this.seenEventIds = new Set();
        this.heartbeatTimer = null;
        this.reconnectTimer = null;

        this.restoreLastSeen();
        this.connect();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const query = new URLSearchParams();
        if (this.authToken) {
            query.set('token', this.authToken);
        }
        if (this.accountUuid) {
            query.set('account_uuid', this.accountUuid);
        }

        const queryString = query.toString();
        const url = `${protocol}//${window.location.host}${CHATLAB_WS_PATH}${queryString ? `?${queryString}` : ''}`;
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            const wasReconnect = this.hasConnectedOnce;
            this.hasConnectedOnce = true;
            this.reconnectAttempts = 0;
            this.dispatch('connected', { simulationId: this.simulationId });
            this.startHeartbeat();
            this.sendSessionEvent(wasReconnect);
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleEnvelope(data);
            } catch (error) {
                console.error('[SimulationSocket] Failed to parse inbound event:', error);
            }
        };

        this.ws.onclose = (event) => {
            this.stopHeartbeat();
            this.sessionEstablished = false;
            this.dispatch('disconnected', { code: event.code, reason: event.reason });

            if (!this.manuallyClosed) {
                this.scheduleReconnect();
            }
        };

        this.ws.onerror = (error) => {
            console.error('[SimulationSocket] WebSocket error:', error);
        };
    }

    sendSessionEvent(isReconnect) {
        const hasReplayAnchor = typeof this.lastSeenEventId === 'string' && this.lastSeenEventId.length > 0;
        const eventType = isReconnect && hasReplayAnchor ? 'session.resume' : 'session.hello';
        const payload = { simulation_id: this.simulationId };
        if (hasReplayAnchor) {
            payload.last_event_id = this.lastSeenEventId;
        }
        this.send(eventType, payload);
    }

    handleEnvelope(envelope) {
        if (!envelope || typeof envelope !== 'object') {
            console.warn('[SimulationSocket] Ignoring malformed envelope:', envelope);
            return;
        }

        const { event_id: eventId, event_type: eventType, created_at: createdAt, correlation_id: correlationId, payload } = envelope;
        if (!eventId || !eventType || !createdAt || typeof payload !== 'object') {
            console.warn('[SimulationSocket] Ignoring incomplete envelope:', envelope);
            return;
        }

        if (this.seenEventIds.has(eventId)) {
            return;
        }
        this.rememberEventId(eventId);

        if (!TRANSIENT_EVENT_TYPES.has(eventType)) {
            this.lastSeenEventId = eventId;
            this.persistLastSeen();
        }

        if (eventType === 'session.ready' || eventType === 'session.resumed') {
            this.sessionEstablished = true;
        }

        if (eventType === 'session.resync_required') {
            this.clearLastSeen();
            if (this.onResyncRequired) {
                this.onResyncRequired(envelope);
            }
        }

        const detail = {
            ...payload,
            event_id: eventId,
            event_type: eventType,
            correlation_id: correlationId,
            created_at: createdAt,
        };
        this.dispatch(eventType, detail);
    }

    rememberEventId(eventId) {
        if (this.seenEventIds.size >= this.maxSeenEventIds) {
            const retained = Array.from(this.seenEventIds).slice(Math.floor(this.maxSeenEventIds / 2));
            this.seenEventIds = new Set(retained);
        }
        this.seenEventIds.add(eventId);
    }

    restoreLastSeen() {
        try {
            const stored = sessionStorage.getItem(this.storageKey);
            if (!stored) {
                return;
            }
            const data = JSON.parse(stored);
            if (typeof data?.eventId === 'string' && data.eventId.length > 0) {
                this.lastSeenEventId = data.eventId;
            }
        } catch (error) {
            console.warn('[SimulationSocket] Failed to restore last_event_id:', error);
        }
    }

    persistLastSeen() {
        try {
            if (!this.lastSeenEventId) {
                sessionStorage.removeItem(this.storageKey);
                return;
            }
            sessionStorage.setItem(this.storageKey, JSON.stringify({ eventId: this.lastSeenEventId }));
        } catch (error) {
            console.warn('[SimulationSocket] Failed to persist last_event_id:', error);
        }
    }

    clearLastSeen() {
        this.lastSeenEventId = null;
        try {
            sessionStorage.removeItem(this.storageKey);
        } catch (error) {
            console.warn('[SimulationSocket] Failed to clear last_event_id:', error);
        }
    }

    scheduleReconnect() {
        if (this.manuallyClosed) {
            return;
        }
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('[SimulationSocket] Max reconnect attempts reached');
            return;
        }
        this.reconnectAttempts += 1;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => this.connect(), delay);
    }

    startHeartbeat() {
        this.stopHeartbeat();
        this.heartbeatTimer = setInterval(() => {
            if (!this.sessionEstablished || !this.isConnected) {
                return;
            }
            this.send('ping', { client_timestamp: new Date().toISOString() });
        }, this.heartbeatIntervalMs);
    }

    stopHeartbeat() {
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = null;
    }

    dispatch(type, detail) {
        window.dispatchEvent(new CustomEvent(`sim:${type}`, {
            detail,
            bubbles: true,
            cancelable: true,
        }));
    }

    send(eventType, payload = {}, correlationId = null) {
        if (!this.isConnected) {
            console.warn('[SimulationSocket] Cannot send event on a closed socket:', eventType);
            return;
        }
        this.ws.send(JSON.stringify({
            event_type: eventType,
            correlation_id: correlationId,
            payload,
        }));
    }

    close() {
        this.manuallyClosed = true;
        this.stopHeartbeat();
        clearTimeout(this.reconnectTimer);
        if (this.ws) {
            this.ws.close();
        }
    }

    get isConnected() {
        return Boolean(this.ws && this.ws.readyState === WebSocket.OPEN);
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = SimulationSocket;
}
window.SimulationSocket = SimulationSocket;
