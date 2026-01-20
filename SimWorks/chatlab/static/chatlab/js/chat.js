/**
 * Chat form state - Alpine component for message input
 */
function chatFormState({ isLocked, isFeedbackContinuation }) {
    return {
        isLocked,
        isFeedbackContinuation,
        messageText: '',
        showEmojiPicker: false,
        init() {
            this.syncFromRoot();
        },
        toggleEmojiPicker() {
            this.showEmojiPicker = !this.showEmojiPicker;
        },
        handleInput() {
            this.autoResize();
            this.notifyTyping();
        },
        notifyTyping() {
            this.$dispatch('form:typing');
        },
        autoResize() {
            if (this.$refs.messageInput) {
                this.$refs.messageInput.style.height = 'auto';
                this.$refs.messageInput.style.height = `${this.$refs.messageInput.scrollHeight}px`;
            }
        },
        send() {
            if (this.isLocked) return;

            // Dispatch event with message content to parent ChatManager
            this.$dispatch('form:send', { messageText: this.messageText });

            this.messageText = '';  // Clear locally after dispatch
            this.showEmojiPicker = false;
            this.autoResize();
        },
        sendFromMobile() {
            this.send();
        },
        syncFromRoot() {
            // Form now manages its own state via $dispatch events
        },
        placeholderText() {
            if (this.isLocked) return 'Simulation locked — chat is read-only';
            if (this.isFeedbackContinuation) return 'Message Stitch to continue feedback conversation';
            return 'Message';
        },
        messageAriaLabel() {
            return this.isLocked ? 'Simulation locked — chat is read-only' : 'Message';
        },
        sendAriaLabel() {
            return this.isLocked ? 'Send message (disabled while simulation is locked)' : 'Send message';
        },
        emojiAriaLabel() {
            return this.showEmojiPicker ? 'Hide emoji picker' : 'Insert emoji';
        }
    };
}

/**
 * ChatManager - Alpine component using SimulationSocket for WebSocket communication
 *
 * Uses SimulationSocket internally and listens for sim:* events via EventBus.
 * Tool refresh is handled declaratively by ToolManager.
 */
function ChatManager(simulation_id, currentUser) {
    return {
        currentUser,
        simulation_id,
        socket: null,
        eventBus: null,
        toolManager: null,
        messageText: '',
        typingTimeout: null,
        lastTypedTime: 0,
        typingUsers: [],
        hasMoreMessages: true,
        systemDisplayInitials: '',
        systemDisplayName: '',
        feedbackContinueConversation: false,
        isChatLocked: false,

        init() {
            this.messageInput = document.getElementById('chat-message-input');
            this.messageForm = document.getElementById('chat-form');
            this.messagesDiv = document.getElementById('chat-messages');
            this.simMetadataDiv = document.getElementById('simulation_metadata_tool');
            this.patientMetadataDiv = document.getElementById('patient_history_tool');
            this.csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            this.newMessageBtn = document.getElementById('new-message-btn');

            // Get DOM data attributes
            const simulationContext = document.getElementById('context');
            this.feedbackContinueConversation = simulationContext?.dataset.feedbackContinuation === 'true';
            this.isChatLocked = simulationContext?.dataset.isChatLocked === 'true';

            // Content mode for server responses
            this.contentMode = 'fullHtml';

            // Initialize WebSocket via SimulationSocket
            this.initializeSocket();

            // Initialize EventBus and ToolManager
            this.initializeEventBus();
            this.initializeToolManager();

            // Setup event listeners
            this.setupEventListeners();
            this.loadOlderMessages();

            this.newMessageBtn.addEventListener('click', () => {
                this.messagesDiv.scrollTop = this.messagesDiv.scrollHeight;
                this.newMessageBtn.classList.add('hidden');
            });

            this.messagesDiv.addEventListener('scroll', () => {
                if (this.isScrolledToBottom()) {
                    this.newMessageBtn.classList.add('hidden');
                    this.newMessageBtn.classList.remove('bounce');
                }
                // Autoload older messages when at the top
                if (this.messagesDiv.scrollTop === 0 && this.hasMoreMessages) {
                    this.loadOlderMessages();
                }
            });
        },

        /**
         * Initialize SimulationSocket
         */
        initializeSocket() {
            // Create socket instance (from simulation-socket.js)
            this.socket = new SimulationSocket(this.simulation_id, {
                contentMode: this.contentMode
            });
        },

        /**
         * Initialize EventBus and subscribe to chat-related events
         */
        initializeEventBus() {
            this.eventBus = new SimulationEventBus();
            this.eventBus.attachSocket(this.socket);

            // Subscribe to chat UI events only
            this.eventBus.on('init_message', (data) => this.handleInitMessage(data));
            this.eventBus.on('chat.message_created', (data) => this.handleChatMessage(data));
            this.eventBus.on('typing', (data) => this.handleTyping(data, true));
            this.eventBus.on('stopped_typing', (data) => this.handleTyping(data, false));
            this.eventBus.on('message_status_update', (data) => this.handleMessageStatusUpdate(data));
            this.eventBus.on('error', (data) => this.handleError(data));

            // Feedback continuation events (UI state only)
            this.eventBus.on('simulation.feedback.continue_conversation', () => {
                this.feedbackContinueConversation = true;
            });
            this.eventBus.on('simulation.hotwash.continue_conversation', () => {
                this.feedbackContinueConversation = true;
            });
        },

        /**
         * Initialize ToolManager with declarative tool configuration
         */
        initializeToolManager() {
            this.toolManager = new ToolManager(this.simulation_id, this.eventBus);

            // Declarative tool configuration - tools auto-refresh on events
            this.toolManager.configure({
                'patient_history': {
                    refreshOn: ['chat.message_created'],
                    refreshMode: 'checksum',
                },
                'simulation_metadata': {
                    refreshOn: ['chat.message_created'],
                    refreshMode: 'checksum',
                },
                'simulation_feedback': {
                    refreshOn: ['simulation.feedback_created', 'simulation.hotwash.created'],
                    refreshMode: 'html_inject',
                },
                'patient_results': {
                    refreshOn: ['simulation.metadata.results_created'],
                    refreshMode: 'html_inject',
                },
            });

            // Auto-discover any additional tools not explicitly configured
            this.toolManager.autoDiscover();
        },

        handleInitMessage(data) {
            if (!this.systemDisplayName || this.systemDisplayName === "Unknown") {
                this.systemDisplayName = data.sim_display_name || "Unknown";
            }
            if (!this.systemDisplayInitials || this.systemDisplayInitials === "Unk") {
                this.systemDisplayInitials = data.sim_display_initials || "Unk";
            }
        },

        handleChatMessage(data) {
            const isFromSelf = data.senderId === this.currentUser;
            const isFromSimulatedUser = data.isFromLLM ?? data.isFromAi ?? false;
            const messageId = data.message_id ?? data.id;

            // If from simulated user (AI), stop typing indicator
            if (isFromSimulatedUser) {
                this.simulateSystemTyping(false);

                // Sidebar pulse for new messages
                if (localStorage.getItem('seenSidebarTray') === 'true') {
                    localStorage.removeItem('seenSidebarTray');
                    if (this.sidebarGesture) this.sidebarGesture.shouldPulse = true;
                }
            }

            // Play receive sound for incoming messages
            const receiveSound = document.getElementById("receive-sound");
            if (!isFromSelf && receiveSound) {
                receiveSound.currentTime = 0;
                receiveSound.play().catch(() => {});
            }

            // Deduplication check
            if (messageId && this._messageExists(messageId)) {
                console.debug("[ChatManager] Skipping duplicate message", messageId);
                return;
            }

            // For AI messages, fetch server-rendered HTML via HTMX
            // This ensures HTML structure matches server templates
            if (isFromSimulatedUser && messageId) {
                this._fetchAndAppendMessage(messageId);
                return;
            }

            // For user's own messages (echoed back), use JS rendering for immediate feedback
            const status = isFromSelf ? data.status || 'delivered' : null;
            const displayName = data.display_name || data.displayName || data.username || 'Unknown';

            // Parse content
            let content = data.content;
            if (typeof content === 'string' && content.startsWith('"') && content.endsWith('"')) {
                try {
                    content = JSON.parse(content);
                } catch (e) {
                    console.warn("Failed to parse message content", e);
                }
            }

            const isFeedbackConversation = !!data.feedbackConversation;
            this.appendMessage(
                content,
                isFromSelf,
                isFeedbackConversation,
                status,
                displayName,
                messageId,
                data.mediaList ?? []
            );

            if (this.messagesDiv.scrollHeight <= this.messagesDiv.clientHeight + 100) {
                this.messagesDiv.scrollTop = this.messagesDiv.scrollHeight;
            }
        },

        /**
         * Check if a message with the given ID already exists in the DOM
         */
        _messageExists(messageId) {
            return !!this.messagesDiv.querySelector(`[data-message-id="${messageId}"]`);
        },

        /**
         * Fetch server-rendered message HTML via HTMX and append to chat
         */
        _fetchAndAppendMessage(messageId) {
            const url = `/chatlab/simulation/${this.simulation_id}/message/${messageId}/`;

            htmx.ajax('GET', url, {
                target: '#chat-messages',
                swap: 'beforeend',
            }).then(() => {
                this._handleScrollBehavior(false);
            }).catch((err) => {
                console.error("[ChatManager] Failed to fetch message:", err);
            });
        },

        handleTyping(data, started) {
            if (data.username !== this.currentUser) {
                this.updateTypingUsers(data, started);
            }
        },

        handleMessageStatusUpdate(data) {
            const existing = this.messagesDiv.querySelector(`[data-message-id="${data.id}"]`);
            if (existing) {
                const alpineRoot = existing.querySelector(".status-icons");
                if (alpineRoot && alpineRoot._x_dataStack) {
                    const alpineState = alpineRoot._x_dataStack[0];
                    if (data.status === "delivered") {
                        alpineState.delivered = true;
                    }
                    if (data.status === "read") {
                        alpineState.read = true;
                    }
                }
            }
        },

        handleError(data) {
            alert(data.message);
            window.location.href = data.redirect || "/";
        },

        notifyTyping() {
            const now = Date.now();
            if (!this.typingTimeout && now - this.lastTypedTime > 2000) {
                this.socket.send('typing', { username: this.currentUser });
                this.lastTypedTime = now;
            }

            clearTimeout(this.typingTimeout);
            this.typingTimeout = setTimeout(() => {
                this.socket.send('stopped_typing', { username: this.currentUser });
                this.typingTimeout = null;
            }, 1000);
        },

        isScrolledToBottom() {
            return this.messagesDiv.scrollHeight - this.messagesDiv.scrollTop <= this.messagesDiv.clientHeight + 50;
        },

        setupEventListeners() {
            // No additional event listeners currently
        },

        /**
         * Send a message via REST API instead of WebSocket.
         *
         * Flow:
         * 1. POST to /api/v1/simulations/{id}/messages/
         * 2. Server creates user message, enqueues AI response
         * 3. Returns 202 Accepted
         * 4. AI response arrives via WebSocket broadcast
         */
        async sendMessage() {
            const message = this.messageText.trim();
            if (!message || this.isChatLocked) return;

            // Optimistic UI: show message immediately
            this.appendMessage(
                message,
                true,
                this.feedbackContinueConversation,
                'sent',
                this.currentUser,
            );

            this.messageText = '';

            // Play send sound
            const sendSound = document.getElementById("send-sound");
            if (sendSound) {
                sendSound.currentTime = 0;
                sendSound.play().catch(() => {});
            }

            // Show typing indicator for AI response
            this.simulateSystemTyping(true);

            try {
                const response = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/messages/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                        body: JSON.stringify({
                            content: message,
                            message_type: 'text',
                        }),
                    }
                );

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${response.status}`);
                }

                // 202 Accepted - AI response will arrive via WebSocket
                console.debug('[ChatManager] Message sent via API, awaiting AI response via WebSocket');
            } catch (error) {
                console.error('[ChatManager] Failed to send message:', error);
                this.simulateSystemTyping(false);
                alert(`Failed to send message: ${error.message}`);
            }
        },

        /**
         * Handle form:send event dispatched from chatFormState
         */
        async handleFormSend(detail) {
            this.messageText = detail.messageText;
            await this.sendMessage();
        },

        appendMessage(content, isFromSelf, isFeedbackConversation, status = "", displayName = "", messageId = null, mediaList = []) {
            console.info("[ChatManager] New message!", { content, isFromSelf, status, displayName, isFeedbackConversation });

            content = this._coerceContent(content);
            status = status || "";

            if (this._isDuplicateMessage(content, messageId)) return;

            if (!isFromSelf && displayName === "") {
                displayName = this.systemDisplayName;
            }

            const bubble = this._buildMessageBubble(content, isFromSelf, displayName, status, mediaList);
            if (messageId) bubble.dataset.messageId = messageId;

            this.messagesDiv.appendChild(bubble);
            this._handleScrollBehavior(isFromSelf);
        },

        _coerceContent(content) {
            if (typeof content === 'string') {
                try {
                    if (content.startsWith('"') && content.endsWith('"')) {
                        return JSON.parse(content);
                    }
                } catch (e) {
                    console.warn("Failed to parse message content", e);
                }
            }
            if (typeof content !== 'string') {
                return '';
            }
            return this.escapeHtml(content);
        },

        _isDuplicateMessage(content, messageId) {
            let existing = null;

            if (messageId) {
                existing = this.messagesDiv.querySelector(`[data-message-id="${messageId}"]`);
            }

            if (!existing && content) {
                existing = Array.from(this.messagesDiv.children).find(div =>
                    div.textContent.includes(content)
                );
                if (existing && messageId) {
                    existing.dataset.messageId = messageId;
                }
            }

            if (existing) {
                console.debug("[ChatManager] Skipping duplicate message", messageId || "(no id)");
                return true;
            }

            return false;
        },

        _buildMessageBubble(content, isFromSelf, displayName, status, mediaList) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `chat-bubble ${isFromSelf ? 'outgoing' : 'incoming'}`;

            const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            const mediaHtml = this._renderMediaHtml(mediaList);

            messageDiv.innerHTML = `
                ${!isFromSelf ? `<strong class="sender-name">${this.escapeHtml(displayName)}</strong>` : ''}
                ${mediaHtml}
                ${content}
                <div class="timestamp">
                    <span class="bubble-time">${timestamp}</span>
                    ${isFromSelf ? this._renderStatusIcons(status) : ''}
                </div>
            `;
            return messageDiv;
        },

        _renderMediaHtml(mediaList) {
            if (!Array.isArray(mediaList) || mediaList.length === 0) return '';
            return `
                <div class="media-container">
                    ${mediaList.map(media => `
                        <img src="${media.url}" class="media-image" alt="media-${media.id}">
                    `).join('')}
                </div>
            `;
        },

        _renderStatusIcons(status) {
            const delivered = !!status;
            const read = status === 'read';
            return `
                <span class="status-icons" x-data="{ delivered: ${delivered}, read: ${read} }">
                    <span class="iconify status-icon delivered-icon" data-icon="fa6-regular:circle-check" x-show="delivered"></span>
                    <span class="iconify status-icon read-icon" data-icon="fa6-regular:circle-check" x-show="read"></span>
                </span>
            `;
        },

        _handleScrollBehavior(isSender) {
            const wasAtBottom = this.isScrolledToBottom();

            if (isSender || wasAtBottom) {
                this.messagesDiv.scrollTo({ top: this.messagesDiv.scrollHeight, behavior: 'smooth' });
            } else {
                this.newMessageBtn.classList.remove('hidden', 'bounce');
                this.newMessageBtn.classList.add('bounce');
                setTimeout(() => this.newMessageBtn.classList.remove('bounce'), 1000);
            }
        },

        escapeHtml(unsafe) {
            return unsafe
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        },

        loadOlderMessages() {
            console.debug("[ChatManager] loadOlderMessages() called");
            const container = document.getElementById('chat-messages');
            const firstMessage = container.firstElementChild;
            const messageId = firstMessage?.dataset?.messageId || null;

            const loadButton = document.getElementById('load-older-btn');
            if (loadButton) {
                loadButton.disabled = true;
                loadButton.textContent = "Loading...";
            }

            if (messageId) {
                let anchor = document.getElementById('message-load-anchor');
                if (!anchor) {
                    anchor = document.createElement('div');
                    anchor.id = 'message-load-anchor';
                    container.prepend(anchor);
                }

                const previousHeight = container.scrollHeight;

                anchor.setAttribute('hx-get', `/chatlab/simulation/${this.simulation_id}/refresh/older-input/?before=${messageId}`);
                anchor.setAttribute('hx-swap', 'beforebegin');
                anchor.setAttribute('hx-trigger', 'load');
                htmx.process(anchor);

                htmx.on(anchor, 'htmx:afterSwap', () => {
                    const addedHeight = container.scrollHeight - previousHeight;
                    container.scrollTop += addedHeight;
                });

                fetch(`/chatlab/simulation/${this.simulation_id}/refresh/older-input/?before=${messageId}`)
                    .then(response => response.text())
                    .then(html => {
                        if (!html.includes('data-message-id')) {
                            this.hasMoreMessages = false;
                            if (loadButton) loadButton.style.display = "none";
                        } else {
                            if (loadButton) {
                                loadButton.disabled = false;
                                loadButton.textContent = "Load Older Messages";
                            }
                        }
                    });
            }
        },

        updateTypingUsers(data, started = true) {
            const displayName = data.display_name || data.username || 'Someone';
            const displayInitials = data.display_initials || 'Unk';
            if (!started) {
                this.typingUsers = this.typingUsers.filter(u => u.username !== data.username);
            } else {
                const alreadyTyping = this.typingUsers.some(u => u.username === data.username);
                if (!alreadyTyping) {
                    this.typingUsers.push({ username: data.username, displayInitials });
                }
            }
            console.debug(
                '[ChatManager]',
                data.username,
                (started ? 'started' : 'stopped'), 'typing.',
                this.typingUsers.length, 'users typing:',
                JSON.stringify(this.typingUsers)
            );
        },

        simulateSystemTyping(started = true) {
            const dataSim = {
                username: 'System',
                display_initials: this.systemDisplayInitials || 'Unk',
                display_name: this.systemDisplayName || 'Someone'
            };
            this.updateTypingUsers(dataSim, started);
        },

        initScrollWatcher() {
            console.debug("[ChatManager] initScrollWatcher() called");
        },
    };
}

// Export globally
window.ChatManager = ChatManager;
window.chatFormState = chatFormState;

/**
 * Sidebar gesture handling for mobile - swipe to open/close
 */
function sidebarGesture() {
    return {
        shouldPulse: localStorage.getItem('seenSidebarTray') !== 'true',
        sidebarOpen: false,
        startX: null,
        endX: null,
        swipeThreshold: 40,

        openSidebar() {
            this.sidebarOpen = true;
            this.justOpened = true;
            localStorage.setItem('seenSidebarTray', 'true');
            this.shouldPulse = false;

            setTimeout(() => {
                this.justOpened = false;
            }, 50);
        },

        startTouch(event) {
            if (event.target.closest('#chat-form')) {
                this.startX = null;
                this.endX = null;
                return;
            }

            this.startX = event.changedTouches[0].screenX;
            this.endX = this.startX;
        },

        moveTouch(event) {
            if (this.startX === null) return;
            this.endX = event.changedTouches[0].screenX;
        },

        endTouch() {
            if (this.startX === null) return;
            const diff = this.endX - this.startX;

            if (!this.sidebarOpen && this.startX > 10 && this.startX < 60 && diff > this.swipeThreshold) {
                this.openSidebar();
            } else if (this.sidebarOpen && diff < -this.swipeThreshold) {
                this.closeSidebar();
            }

            this.startX = null;
            this.endX = null;
        },

        maybeClose(event) {
            if (window.innerWidth < 768 && !this.justOpened) {
                this.closeSidebar();
            }
        },

        closeSidebar() {
            const sidebar = document.querySelector('.sim-sidebar');
            if (!sidebar) {
                this.sidebarOpen = false;
                return;
            }

            sidebar.classList.add('slide-out');

            setTimeout(() => {
                sidebar.classList.remove('slide-out');
                sidebar.classList.remove('visible');
                this.sidebarOpen = false;
            }, 250);
        }
    };
}
