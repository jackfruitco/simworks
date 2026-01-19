/**
 * Alpine.js components for simulation UI
 *
 * Provides:
 * - simTimer: Simulation timer with optional countdown and auto-end
 * - sidebarState: Collapsible sidebar section state
 * - toolPanelState: Individual tool panel toggle state
 */

/**
 * Simulation timer component.
 *
 * @param {number} startTimestamp - Unix timestamp (ms) when simulation started
 * @param {number|null} endTimestamp - Unix timestamp (ms) when simulation ended (null if ongoing)
 * @param {number|null} timeLimitMs - Time limit in milliseconds (null for no limit)
 * @returns {Object} Alpine.js component
 */
function simTimer(startTimestamp, endTimestamp = null, timeLimitMs = null) {
    return {
        startTimestamp,
        endTimestamp,
        timeLimitMs,

        formatted: '00:00',
        countdown: timeLimitMs !== null,
        ended: endTimestamp !== null,
        intervalId: null,
        csrfToken: document.querySelector('[name=csrfmiddlewaretoken]')?.value ?? "",

        start() {
            if (this.ended) {
                this.updateStatic();
            } else {
                this.updateLive();
                this.intervalId = setInterval(() => this.updateLive(), 1000);
            }
        },

        updateStatic() {
            if (this.startTimestamp && this.endTimestamp) {
                const elapsedMs = this.endTimestamp - this.startTimestamp;
                this.formatted = this.formatDuration(elapsedMs);
            } else {
                this.formatted = "00:00";
            }
        },

        updateLive() {
            const now = Date.now();
            const elapsedMs = now - this.startTimestamp;

            if (this.countdown) {
                const remainingMs = this.timeLimitMs - elapsedMs;
                if (remainingMs <= 0) {
                    this.autoEnd();
                    this.formatted = '00:00';
                } else {
                    this.formatted = this.formatDuration(remainingMs);
                }
            } else {
                this.formatted = this.formatDuration(elapsedMs);
            }
        },

        autoEnd() {
            if (this.intervalId) {
                clearInterval(this.intervalId);
            }
            if (!this.ended) {
                const context = document.getElementById('context');
                const endUrl = context?.dataset.endSimulationUrl;
                if (endUrl) {
                    fetch(endUrl, {
                        method: "POST",
                        headers: {
                            "X-CSRFToken": this.csrfToken,
                        },
                    });
                }
                this.ended = true;
            }
        },

        formatDuration(ms) {
            const totalSeconds = Math.floor(ms / 1000);
            const hours = Math.floor(totalSeconds / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = totalSeconds % 60;

            if (hours > 0) {
                return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
            } else {
                return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
            }
        }
    };
}

/**
 * Sidebar section state manager.
 *
 * Persists open/closed state per simulation to localStorage.
 *
 * @param {number|string} simulationId - Simulation ID for namespacing storage keys
 * @returns {Object} Alpine.js component
 */
function sidebarState(simulationId) {
    return {
        sections: {
            simMetadata: JSON.parse(localStorage.getItem(`simMetadataOpen_${simulationId}`) ?? 'true'),
            patientMetadata: JSON.parse(localStorage.getItem(`patientMetadataOpen_${simulationId}`) ?? 'true'),
            feedback: JSON.parse(localStorage.getItem(`simFeedbackOpen_${simulationId}`) ?? 'true'),
        },
        toggle(section) {
            this.sections[section] = !this.sections[section];
            localStorage.setItem(`${section}Open_${simulationId}`, JSON.stringify(this.sections[section]));
        },
        isOpen(section) {
            return this.sections[section];
        }
    };
}

/**
 * Tool panel toggle state.
 *
 * Persists open/closed state per tool per simulation to localStorage.
 *
 * @param {string} toolName - Tool identifier
 * @param {number|string} simulationId - Simulation ID for namespacing storage keys
 * @returns {Object} Alpine.js component
 */
function toolPanelState(toolName, simulationId) {
    const storageKey = `toolOpen_${toolName}_${simulationId}`;
    const storedValue = localStorage.getItem(storageKey);
    return {
        toolName,
        panelId: `${toolName}_tool`,
        storageKey,
        isOpen: storedValue === null ? true : JSON.parse(storedValue),
        toggle() {
            this.isOpen = !this.isOpen;
            localStorage.setItem(this.storageKey, JSON.stringify(this.isOpen));
        },
    };
}
