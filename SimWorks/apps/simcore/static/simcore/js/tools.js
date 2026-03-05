// Simulation Tools Alpine.js Components

document.addEventListener('alpine:init', () => {
    // Sidebar state management for tools
    Alpine.store('toolStates', {
        openTools: new Set(),

        toggle(toolName) {
            if (this.openTools.has(toolName)) {
                this.openTools.delete(toolName);
            } else {
                this.openTools.add(toolName);
            }
        },

        isOpen(toolName) {
            return this.openTools.has(toolName);
        },

        openAll() {
            // Get all tool names and open them
            document.querySelectorAll('[data-tool-name]').forEach(el => {
                this.openTools.add(el.dataset.toolName);
            });
        },

        closeAll() {
            this.openTools.clear();
        }
    });
});

// Sidebar state component
function sidebarState(simulationId) {
    return {
        simulationId: simulationId,
        openTools: new Set(['simulation_metadata']), // Open metadata by default

        init() {
            // Load saved state from localStorage
            const saved = localStorage.getItem(`sim_${this.simulationId}_tools`);
            if (saved) {
                try {
                    this.openTools = new Set(JSON.parse(saved));
                } catch (e) {
                    console.error('Failed to load tool states:', e);
                }
            }
        },

        toggle(toolName) {
            if (this.openTools.has(toolName)) {
                this.openTools.delete(toolName);
            } else {
                this.openTools.add(toolName);
            }
            this.saveState();
        },

        isOpen(toolName) {
            // Handle both the check call and returning boolean
            if (arguments.length === 0) {
                // Called without args in x-show context
                return false;
            }
            return this.openTools.has(toolName);
        },

        saveState() {
            try {
                localStorage.setItem(
                    `sim_${this.simulationId}_tools`,
                    JSON.stringify(Array.from(this.openTools))
                );
            } catch (e) {
                console.error('Failed to save tool states:', e);
            }
        },

        expandAll() {
            document.querySelectorAll('[data-tool-name]').forEach(el => {
                this.openTools.add(el.dataset.toolName);
            });
            this.saveState();
        },

        collapseAll() {
            this.openTools.clear();
            this.saveState();
        }
    };
}

// Results filter component
function resultsFilter() {
    return {
        activeTab: 'all',
        searchQuery: '',
        sortBy: 'date',

        tabs: ['all', 'labs', 'imaging'],

        setTab(tab) {
            this.activeTab = tab;
        },

        filterResults(results) {
            let filtered = results;

            // Filter by tab
            if (this.activeTab !== 'all') {
                filtered = filtered.filter(r => r.type === this.activeTab);
            }

            // Filter by search
            if (this.searchQuery) {
                const query = this.searchQuery.toLowerCase();
                filtered = filtered.filter(r =>
                    r.name.toLowerCase().includes(query) ||
                    r.value.toLowerCase().includes(query)
                );
            }

            // Sort
            filtered.sort((a, b) => {
                if (this.sortBy === 'date') {
                    return new Date(b.date) - new Date(a.date);
                } else if (this.sortBy === 'name') {
                    return a.name.localeCompare(b.name);
                }
                return 0;
            });

            return filtered;
        }
    };
}

// Feedback expander component
function feedbackExpander() {
    return {
        expandedItems: new Set(),

        toggle(itemId) {
            if (this.expandedItems.has(itemId)) {
                this.expandedItems.delete(itemId);
            } else {
                this.expandedItems.add(itemId);
            }
        },

        isExpanded(itemId) {
            return this.expandedItems.has(itemId);
        },

        expandAll() {
            document.querySelectorAll('[data-feedback-id]').forEach(el => {
                this.expandedItems.add(el.dataset.feedbackId);
            });
        },

        collapseAll() {
            this.expandedItems.clear();
        }
    };
}

// Order request modal component
function orderRequestModal() {
    return {
        open: false,
        selectedOrders: new Set(),
        searchQuery: '',

        show() {
            this.open = true;
            document.body.style.overflow = 'hidden';
        },

        hide() {
            this.open = false;
            document.body.style.overflow = '';
        },

        toggleOrder(orderId) {
            if (this.selectedOrders.has(orderId)) {
                this.selectedOrders.delete(orderId);
            } else {
                this.selectedOrders.add(orderId);
            }
        },

        isSelected(orderId) {
            return this.selectedOrders.has(orderId);
        },

        async submitOrders() {
            const orders = Array.from(this.selectedOrders);

            try {
                const response = await fetch(this.$el.dataset.submitUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify({ submitted_orders: orders })
                });

                if (response.ok) {
                    // Show success toast
                    if (window.Alpine?.store('toasts')) {
                        window.Alpine.store('toasts').add('Orders submitted successfully', 'success');
                    }

                    this.hide();
                    this.selectedOrders.clear();

                    // Trigger tool refresh
                    htmx.trigger('#patient_results_tool', 'refresh');
                } else {
                    throw new Error('Failed to submit orders');
                }
            } catch (error) {
                console.error('Error submitting orders:', error);
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add('Failed to submit orders', 'error');
                }
            }
        }
    };
}

// Copy to clipboard utility
function copyToClipboard(text, label = 'Text') {
    navigator.clipboard.writeText(text).then(() => {
        if (window.Alpine?.store('toasts')) {
            window.Alpine.store('toasts').add(`${label} copied to clipboard`, 'success');
        }
    }).catch(err => {
        console.error('Failed to copy:', err);
        if (window.Alpine?.store('toasts')) {
            window.Alpine.store('toasts').add('Failed to copy to clipboard', 'error');
        }
    });
}

// Tool refresh handler
function refreshTool(toolName, simulationId) {
    const toolElement = document.getElementById(`${toolName}_tool`);
    if (!toolElement) return;

    // Show loading state
    toolElement.classList.add('tool-skeleton');

    // Use HTMX to refresh
    htmx.ajax('GET', `/tools/${toolName}/refresh/${simulationId}/`, {
        target: `#${toolName}_tool`,
        swap: 'outerHTML'
    });
}

// Check for tool updates
async function checkToolUpdates(simulationId) {
    const tools = document.querySelectorAll('[data-tool-name][data-checksum]');

    for (const tool of tools) {
        const toolName = tool.dataset.toolName;
        const currentChecksum = tool.dataset.checksum;

        try {
            const response = await fetch(`/tools/${toolName}/checksum/${simulationId}/`);
            const data = await response.json();

            if (data.checksum !== currentChecksum) {
                // Checksum changed, refresh the tool
                console.log(`Tool ${toolName} has updates, refreshing...`);
                refreshTool(toolName, simulationId);
            }
        } catch (error) {
            console.error(`Failed to check updates for ${toolName}:`, error);
        }
    }
}

// Helper function to get CSRF token
function getCsrfToken() {
    const token = document.querySelector('[name=csrfmiddlewaretoken]');
    if (token) {
        return token.value;
    }

    // Fallback: try to get from cookie
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return value;
        }
    }

    return '';
}

// Auto-refresh tools every 30 seconds
let toolRefreshInterval = null;

function startToolAutoRefresh(simulationId, intervalMs = 30000) {
    if (toolRefreshInterval) {
        clearInterval(toolRefreshInterval);
    }

    toolRefreshInterval = setInterval(() => {
        checkToolUpdates(simulationId);
    }, intervalMs);
}

function stopToolAutoRefresh() {
    if (toolRefreshInterval) {
        clearInterval(toolRefreshInterval);
        toolRefreshInterval = null;
    }
}

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    stopToolAutoRefresh();
});
