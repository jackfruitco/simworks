/**
 * ToolManager - Declarative tool refresh coordination.
 *
 * Replaces scattered `window.simulationManager.checkTools()` calls with
 * declarative configuration. Tools automatically refresh when subscribed
 * events are triggered via the SimulationEventBus.
 *
 * Features:
 * - Declarative tool registration with event subscriptions
 * - Checksum-based refresh (only refresh if data changed)
 * - HTML injection mode (for events that include rendered HTML)
 * - Auto-discovery of tools from DOM
 *
 * Usage:
 *   const toolManager = new ToolManager(simulationId, eventBus);
 *
 *   // Declarative configuration
 *   toolManager.configure({
 *       'patient_history': {
 *           refreshOn: ['chat.message_created'],
 *           refreshMode: 'checksum',  // or 'always' or 'html_inject'
 *       },
 *       'simulation_feedback': {
 *           refreshOn: ['simulation.feedback_created'],
 *           refreshMode: 'html_inject',
 *       },
 *   });
 *
 *   // Or register individual tools
 *   toolManager.registerTool('patient_results', {
 *       refreshOn: ['simulation.metadata.results_created'],
 *       refreshMode: 'html_inject',
 *   });
 *
 *   // Auto-discover tools from DOM
 *   toolManager.autoDiscover();
 */
class ToolManager {
    /**
     * Create a new ToolManager.
     * @param {number|string} simulationId - The simulation ID
     * @param {SimulationEventBus} eventBus - The event bus instance
     */
    constructor(simulationId, eventBus) {
        this.simulationId = simulationId;
        this.eventBus = eventBus;

        // Map of toolName -> { checksum, elementId, config, unsubscribers }
        this.tools = new Map();

        console.debug('[ToolManager] Initialized for simulation:', simulationId);
    }

    /**
     * Configure multiple tools at once.
     * @param {Object} config - Configuration object keyed by tool name
     */
    configure(config) {
        for (const [toolName, toolConfig] of Object.entries(config)) {
            this.registerTool(toolName, toolConfig);
        }
    }

    /**
     * Register a single tool.
     * @param {string} toolName - The tool name (matches DOM id pattern: {toolName}_tool)
     * @param {Object} config - Tool configuration
     * @param {string[]} config.refreshOn - Event types to trigger refresh
     * @param {string} config.refreshMode - 'checksum' | 'always' | 'html_inject'
     * @param {string} config.elementId - Override element ID (default: {toolName}_tool)
     */
    registerTool(toolName, config) {
        const elementId = config.elementId || `${toolName}_tool`;
        const element = document.getElementById(elementId);

        if (!element) {
            console.warn(`[ToolManager] Element not found for tool: ${toolName} (${elementId})`);
        }

        const initialChecksum = element?.dataset?.checksum || null;

        const tool = {
            name: toolName,
            elementId,
            checksum: initialChecksum,
            config: {
                refreshOn: config.refreshOn || [],
                refreshMode: config.refreshMode || 'checksum',
            },
            unsubscribers: [],
        };

        // Subscribe to events
        for (const eventType of tool.config.refreshOn) {
            const unsubscribe = this.eventBus.on(eventType, (data, type) => {
                this._handleEvent(toolName, data, type);
            });
            tool.unsubscribers.push(unsubscribe);
        }

        this.tools.set(toolName, tool);

        console.debug(`[ToolManager] Registered tool: ${toolName}`, {
            elementId,
            checksum: initialChecksum,
            refreshOn: tool.config.refreshOn,
            refreshMode: tool.config.refreshMode,
        });
    }

    /**
     * Auto-discover tools from DOM elements with pattern [id$='_tool'].
     * Registers them with no event subscriptions by default.
     */
    autoDiscover() {
        document.querySelectorAll("[id$='_tool']").forEach((div) => {
            const toolName = div.id.replace('_tool', '');

            // Don't override existing configuration
            if (this.tools.has(toolName)) {
                return;
            }

            const initialChecksum = div.dataset.checksum || null;

            this.tools.set(toolName, {
                name: toolName,
                elementId: div.id,
                checksum: initialChecksum,
                config: {
                    refreshOn: [],
                    refreshMode: 'checksum',
                },
                unsubscribers: [],
            });

            console.debug(`[ToolManager] Auto-discovered tool: ${toolName}`, {
                checksum: initialChecksum,
            });
        });
    }

    /**
     * Handle an event for a tool.
     * @param {string} toolName - The tool name
     * @param {Object} data - Event data
     * @param {string} eventType - The event type
     */
    _handleEvent(toolName, data, eventType) {
        const tool = this.tools.get(toolName);
        if (!tool) {
            console.warn(`[ToolManager] Unknown tool: ${toolName}`);
            return;
        }

        console.debug(`[ToolManager] Event ${eventType} triggered for tool: ${toolName}`);

        const mode = tool.config.refreshMode;

        if (mode === 'html_inject' && data?.html) {
            // HTML injection mode - use provided HTML
            this.refreshFromHTML(toolName, data.html);
        } else if (mode === 'always') {
            // Always refresh
            this.refresh(toolName);
        } else {
            // Checksum mode - only refresh if data changed
            this.checkAndRefresh(toolName);
        }
    }

    /**
     * Check checksum and refresh if changed.
     * @param {string} toolName - The tool name
     */
    checkAndRefresh(toolName) {
        const tool = this.tools.get(toolName);
        if (!tool) return;

        fetch(`/tools/${toolName}/checksum/${this.simulationId}/`)
            .then(response => response.json())
            .then(data => {
                if (data.checksum !== tool.checksum) {
                    console.info(`[ToolManager] Checksum changed for ${toolName}, refreshing...`);
                    tool.checksum = data.checksum;
                    this.refresh(toolName);
                } else {
                    console.debug(`[ToolManager] Checksum unchanged for ${toolName}`);
                }
            })
            .catch(error => {
                console.error(`[ToolManager] Failed to fetch checksum for ${toolName}:`, error);
            });
    }

    /**
     * Force refresh a tool via HTMX.
     * @param {string} toolName - The tool name
     */
    refresh(toolName) {
        const tool = this.tools.get(toolName);
        if (!tool) return;

        const targetDiv = document.getElementById(tool.elementId);
        if (!targetDiv) {
            console.warn(`[ToolManager] Element not found: ${tool.elementId}`);
            return;
        }

        htmx.ajax('GET', `/tools/${toolName}/refresh/${this.simulationId}/`, {
            target: targetDiv,
            swap: 'innerHTML',
        });

        console.info(`[ToolManager] Refresh requested for '${toolName}' via HTMX`);
    }

    /**
     * Refresh a tool by injecting HTML directly.
     * @param {string} toolName - The tool name
     * @param {string} html - The HTML to inject
     */
    refreshFromHTML(toolName, html) {
        const tool = this.tools.get(toolName);

        // Try both underscore and hyphenated versions of the ID
        const underscoreId = `${toolName}_tool`;
        const hyphenId = `${toolName.replace(/_/g, '-')}-tool`;

        let element = document.getElementById(underscoreId);
        if (!element) {
            element = document.getElementById(hyphenId);
        }

        if (element) {
            element.innerHTML = html;
            console.info(`[ToolManager] Refreshed '${toolName}' via HTML inject`);
        } else {
            console.warn(`[ToolManager] Could not find element for tool: ${toolName}`);
        }
    }

    /**
     * Check multiple tools (compatibility method for SimulationManager).
     * @param {string[]} toolNames - Array of tool names
     * @param {boolean} forceRefresh - Force refresh without checksum check
     */
    checkTools(toolNames, forceRefresh = false) {
        console.debug(`[ToolManager] Checking tools: ${toolNames.join(', ')}`);

        for (const toolName of toolNames) {
            if (forceRefresh) {
                this.refresh(toolName);
            } else {
                this.checkAndRefresh(toolName);
            }
        }
    }

    /**
     * Unregister a tool and clean up subscriptions.
     * @param {string} toolName - The tool name
     */
    unregisterTool(toolName) {
        const tool = this.tools.get(toolName);
        if (!tool) return;

        // Clean up subscriptions
        for (const unsub of tool.unsubscribers) {
            unsub();
        }

        this.tools.delete(toolName);
        console.debug(`[ToolManager] Unregistered tool: ${toolName}`);
    }

    /**
     * Clean up all tools and subscriptions.
     */
    destroy() {
        for (const [toolName, tool] of this.tools) {
            for (const unsub of tool.unsubscribers) {
                unsub();
            }
        }
        this.tools.clear();
        console.debug('[ToolManager] Destroyed');
    }
}

// Export for module systems and attach to window for global access
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ToolManager;
}
window.ToolManager = ToolManager;
