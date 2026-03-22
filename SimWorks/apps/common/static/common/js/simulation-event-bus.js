/**
 * SimulationEventBus - Event routing layer for simulation components.
 *
 * Provides a subscription-based interface over SimulationSocket's DOM events.
 * Allows components to subscribe to events with wildcards and priority ordering.
 *
 * Features:
 * - Wildcard subscriptions: 'message.*' matches all message events
 * - Priority-based handler ordering
 * - Clean unsubscribe via returned function
 *
 * Usage:
 *   const eventBus = new SimulationEventBus();
 *   eventBus.attachSocket(socket);
 *
 *   // Subscribe to single event
 *   const unsubscribe = eventBus.on('message.item.created', (data) => {
 *       console.log('Message:', data);
 *   });
 *
 *   // Subscribe to multiple events
 *   eventBus.onMany(['typing', 'stopped_typing'], (data) => {
 *       console.log('Typing status changed');
 *   });
 *
 *   // Wildcard subscription
 *   eventBus.on('simulation.*', (data, eventType) => {
 *       console.log('Simulation event:', eventType, data);
 *   });
 *
 *   // Cleanup
 *   unsubscribe();
 *   eventBus.detach();
 */
class SimulationEventBus {
    constructor() {
        // Map of eventType -> Set of {handler, priority, id}
        this.subscriptions = new Map();

        // Wildcard patterns
        this.wildcardSubscriptions = [];

        // Counter for unique subscription IDs
        this.nextId = 1;

        // Bound handler reference for cleanup
        this._boundHandler = null;

        // Track attached socket
        this._socket = null;
    }

    /**
     * Attach to a SimulationSocket to receive events.
     * @param {SimulationSocket} socket - The socket instance to listen to
     */
    attachSocket(socket) {
        if (this._socket) {
            this.detach();
        }

        this._socket = socket;

        // Create bound handler for all sim:* events
        this._boundHandler = (event) => {
            // Extract event type from the custom event name (sim:xxx -> xxx)
            const fullType = event.type;
            const eventType = fullType.startsWith('sim:') ? fullType.slice(4) : fullType;
            this._dispatch(eventType, event.detail);
        };

        // Listen for all sim:* events by using a single capturing listener
        // We'll need to listen for specific event types instead
        this._setupListeners();
    }

    /**
     * Setup listeners for known event types.
     * This is called internally by attachSocket.
     */
    _setupListeners() {
        const eventTypes = [
            'init_message',
            'message.item.created',
            'chat.message_created',
            'typing',
            'stopped_typing',
            'feedback.item.created',
            'simulation.feedback_created',
            'feedback.created',
            'simulation.hotwash.created',
            'simulation.feedback.continue_conversation',
            'simulation.hotwash.continue_conversation',
            'patient.metadata.created',
            'message.delivery.updated',
            'simulation.status.updated',
            'feedback.generation.failed',
            'feedback.generation.updated',
            'patient.results.updated',
            'simulation.metadata.results_created',
            'simulation.state_changed',
            'feedback.failed',
            'feedback.retrying',
            'message_status_update',
            'error',
            'connected',
            'disconnected',
        ];

        this._listeners = [];

        for (const type of eventTypes) {
            const handler = (event) => {
                this._dispatch(type, event.detail);
            };
            window.addEventListener(`sim:${type}`, handler);
            this._listeners.push({ type: `sim:${type}`, handler });
        }
    }

    /**
     * Detach from the current socket and clean up listeners.
     */
    detach() {
        if (this._listeners) {
            for (const { type, handler } of this._listeners) {
                window.removeEventListener(type, handler);
            }
            this._listeners = [];
        }

        this._socket = null;
        this._boundHandler = null;
    }

    /**
     * Subscribe to an event type.
     * @param {string} eventType - Event type to subscribe to (supports wildcards like 'chat.*')
     * @param {Function} handler - Handler function (data, eventType) => void
     * @param {Object} options - Options object
     * @param {number} options.priority - Handler priority (higher = called first, default 0)
     * @returns {Function} Unsubscribe function
     */
    on(eventType, handler, options = {}) {
        const priority = options.priority || 0;
        const id = this.nextId++;

        const subscription = { handler, priority, id };

        // Check if this is a wildcard pattern
        if (eventType.includes('*')) {
            const pattern = this._wildcardToRegex(eventType);
            this.wildcardSubscriptions.push({ pattern, ...subscription });
            this._sortWildcardSubscriptions();

            return () => {
                const index = this.wildcardSubscriptions.findIndex(s => s.id === id);
                if (index !== -1) {
                    this.wildcardSubscriptions.splice(index, 1);
                }
            };
        }

        // Exact match subscription
        if (!this.subscriptions.has(eventType)) {
            this.subscriptions.set(eventType, []);
        }

        const subs = this.subscriptions.get(eventType);
        subs.push(subscription);
        this._sortSubscriptions(eventType);

        return () => {
            const subs = this.subscriptions.get(eventType);
            if (subs) {
                const index = subs.findIndex(s => s.id === id);
                if (index !== -1) {
                    subs.splice(index, 1);
                }
            }
        };
    }

    /**
     * Subscribe to multiple event types with the same handler.
     * @param {string[]} eventTypes - Array of event types to subscribe to
     * @param {Function} handler - Handler function (data, eventType) => void
     * @param {Object} options - Options object
     * @returns {Function} Unsubscribe function that removes all subscriptions
     */
    onMany(eventTypes, handler, options = {}) {
        const unsubscribers = eventTypes.map(type => this.on(type, handler, options));

        return () => {
            unsubscribers.forEach(unsub => unsub());
        };
    }

    /**
     * Dispatch an event to all matching subscribers.
     * @param {string} eventType - The event type
     * @param {Object} data - The event data
     */
    _dispatch(eventType, data) {
        // Exact match subscribers
        const exactSubs = this.subscriptions.get(eventType) || [];
        for (const sub of exactSubs) {
            try {
                sub.handler(data, eventType);
            } catch (e) {
                console.error(`[SimulationEventBus] Handler error for ${eventType}:`, e);
            }
        }

        // Wildcard subscribers
        for (const sub of this.wildcardSubscriptions) {
            if (sub.pattern.test(eventType)) {
                try {
                    sub.handler(data, eventType);
                } catch (e) {
                    console.error(`[SimulationEventBus] Wildcard handler error for ${eventType}:`, e);
                }
            }
        }
    }

    /**
     * Convert a wildcard pattern to a regex.
     * @param {string} pattern - Pattern like 'chat.*' or 'simulation.*.*'
     * @returns {RegExp} Regex for matching
     */
    _wildcardToRegex(pattern) {
        // Escape regex special chars except *
        const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
        // Replace * with non-greedy match
        const regexStr = escaped.replace(/\*/g, '[^.]*');
        return new RegExp(`^${regexStr}$`);
    }

    /**
     * Sort subscriptions by priority (descending).
     * @param {string} eventType - Event type to sort subscriptions for
     */
    _sortSubscriptions(eventType) {
        const subs = this.subscriptions.get(eventType);
        if (subs) {
            subs.sort((a, b) => b.priority - a.priority);
        }
    }

    /**
     * Sort wildcard subscriptions by priority (descending).
     */
    _sortWildcardSubscriptions() {
        this.wildcardSubscriptions.sort((a, b) => b.priority - a.priority);
    }
}

// Export for module systems and attach to window for global access
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SimulationEventBus;
}
window.SimulationEventBus = SimulationEventBus;
