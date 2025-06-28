window.SimulationManager = function(simulation_id) {
    console.debug("[SimulationManager] Script loaded");
    return {
        simulation_id,
        tools: {}, // { toolName: { checksum, elementId } }

        init() {
            console.log("[SimulationManager] Initializing...");

            // Find all tool wrappers
            document.querySelectorAll(".sim-sidebar-wrapper [id$='_tool']").forEach((div) => {
                const toolName = div.id.replace('_tool', '');
                const initialChecksum = div.dataset.checksum || null;

                this.tools[toolName] = {
                    checksum: initialChecksum,
                    elementId: div.id,
                };
                console.debug(`[SimulationManager] Registered tool:`, {
                    toolName,
                    checksum: initialChecksum,
                    elementId: div.id,
                });

                console.debug(`[SimulationManager] Found tool: ${toolName}, checksum: ${initialChecksum}`);
            });
        },

        checkToolChecksum(toolName) {
            const tool = this.tools[toolName];
            if (!tool) {
                console.warn(`[SimulationManager] No tool found with name ${toolName}`);
                return;
            }

            fetch(`/tools/${toolName}/checksum/${this.simulation_id}/`)
                .then(response => response.json())
                .then(data => {
                    if (data.checksum !== tool.checksum) {
                        console.info(`[SimulationManager] Checksum changed for ${toolName}, refreshing...`);
                        this.refreshTool(toolName);
                        console.debug(`[SimulationManager] Refresh triggered for ${toolName}`);
                        tool.checksum = data.checksum; // update after refresh
                    } else {
                        console.debug(`[SimulationManager] Checksum unchanged for ${toolName}`);
                    }
                })
                .catch(error => {
                    console.error(`[SimulationManager] Failed to fetch checksum for ${toolName}`, error);
                });
        },

        checkAllTools() {
            console.debug("[ToolManager] Checking all tools for checksum updates...");
            Object.keys(this.tools).forEach(toolName => {
                this.checkToolChecksum(toolName);
            });
        },

        checkTools(toolNames, forceRefresh = false) {
            console.debug(`[ToolManager] Checking selected tools: ${toolNames.join(', ')}`);
            toolNames.forEach(toolName => {
                if (forceRefresh) {
                    console.info(`[ToolManager] Forcing refresh for ${toolName}`);
                    this.refreshTool(toolName);
                } else {
                    this.checkToolChecksum(toolName);
                }
            });
        },

        refreshTool(toolName) {
            const tool = this.tools[toolName];
            if (!tool) return;

            const targetDiv = document.getElementById(tool.elementId);
            if (!targetDiv) return;

            htmx.ajax('GET', `/tools/${toolName}/refresh/${this.simulation_id}/`, {
                target: targetDiv,
                swap: 'innerHTML'
            });
            console.info(`[ToolManager] Refresh requested '${toolName}' via HTMX request`);
        },

        refreshToolFromHTML(tool, html) {
            const id = `${tool.replaceAll('_', '-')}-tool`;
            const el = document.getElementById(id);
            if (el) {
                el.innerHTML = html;
                console.info(`[ToolManager] Refreshed '${tool}' via HTML inject`);
            } else {
                console.warn(`[ToolManager] Could not find element '${id}'`);
            }
        },
    };
};