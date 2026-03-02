/**
 * Chat form state - Alpine component for message input
 *
 * Reads lock state from the parent ChatManager's active conversation.
 */
function chatFormState({ isLocked }) {
    return {
        isLocked,
        messageText: '',
        showEmojiPicker: false,
        _conversationType: 'simulated_patient',
        init() {
            // Initial lock state comes from server-rendered template.
            // Listen for conversation lock changes dispatched by ChatManager.
            const chatPanel = this.$el.closest('[x-data*="ChatManager"]');
            if (chatPanel) {
                chatPanel.addEventListener('conversation:lock-changed', (e) => {
                    this.isLocked = e.detail.isLocked;
                    this._conversationType = e.detail.conversationType || 'simulated_patient';
                });
            }
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
        handleKeyDown(event) {
            // On mobile/tablet, Enter should create a new line, not send
            // On desktop, Enter sends, Shift+Enter creates new line
            if (event.key === 'Enter' && !event.shiftKey) {
                const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent) ||
                                 ('ontouchstart' in window && window.innerWidth < 1024);

                if (!isMobile) {
                    event.preventDefault();
                    this.send();
                }
                // On mobile, allow default behavior (new line)
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
        placeholderText() {
            if (this.isLocked) return 'This conversation is read-only';
            if (this._conversationType !== 'simulated_patient') {
                return 'Message Stitch...';
            }
            return 'Message';
        },
        messageAriaLabel() {
            return this.isLocked ? 'Conversation is read-only' : 'Message';
        },
        sendAriaLabel() {
            return this.isLocked ? 'Send message (disabled while conversation is locked)' : 'Send message';
        },
        emojiAriaLabel() {
            return this.showEmojiPicker ? 'Hide emoji picker' : 'Insert emoji';
        },
    };
}

/**
 * ChatManager - Alpine component using SimulationSocket for WebSocket communication
 *
 * Uses SimulationSocket internally and listens for sim:* events via EventBus.
 * Tool refresh is handled declaratively by ToolManager.
 *
 * Multi-conversation support:
 *  - conversations[]: loaded from API on init
 *  - activeConversationId: currently visible conversation
 *  - Tab bar rendered when conversations.length > 1
 *  - Messages routed to the correct conversation via conversation_id
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
        isChatLocked: false,

        // --- Multi-conversation state ---
        conversations: [],
        activeConversationId: null,

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

            // Listen for stitch:create events from external buttons (e.g. tools panel)
            this.$el.addEventListener('stitch:create', () => this.createStitchConversation());

            // Load conversations from API, then load messages for active conversation
            this.loadConversations().then(() => {
                this.loadInitialMessages();
            });

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

        // ----- Conversation management -----

        /**
         * Load conversations for this simulation from the REST API.
         */
        async loadConversations() {
            try {
                const resp = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/conversations/`,
                    { headers: { 'X-CSRFToken': this.csrfToken } },
                );
                if (!resp.ok) {
                    console.warn('[ChatManager] Failed to load conversations:', resp.status);
                    return;
                }
                const data = await resp.json();
                this.conversations = (data.items || []).map(c => ({
                    ...c,
                    _unread: 0,
                }));

                // Default to first conversation (patient) if none active
                if (this.conversations.length && !this.activeConversationId) {
                    this.activeConversationId = this.conversations[0].id;
                }

                // Sync form lock state with active conversation
                this._syncFormLock();
            } catch (err) {
                console.error('[ChatManager] Error loading conversations:', err);
            }
        },

        /**
         * Get the currently active conversation object.
         */
        getActiveConversation() {
            return this.conversations.find(c => c.id === this.activeConversationId) || null;
        },

        /**
         * Switch the visible conversation. Reloads messages for the target conversation.
         */
        switchConversation(convId) {
            if (convId === this.activeConversationId) return;

            this.activeConversationId = convId;

            // Reset unread badge for this conversation
            const conv = this.conversations.find(c => c.id === convId);
            if (conv) conv._unread = 0;

            // Sync form lock state
            this._syncFormLock();

            // Reload messages for this conversation via HTMX
            const url = `/chatlab/simulation/${this.simulation_id}/refresh/messages/?conversation_id=${convId}`;
            htmx.ajax('GET', url, { target: '#chat-messages', swap: 'innerHTML' });

            this.hasMoreMessages = true;
        },

        /**
         * Create a Stitch feedback conversation (on-demand) and switch to it.
         */
        async createStitchConversation() {
            try {
                const resp = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/conversations/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                        body: JSON.stringify({ conversation_type: 'simulated_feedback' }),
                    },
                );
                if (resp.ok || resp.status === 201) {
                    await this.loadConversations();
                    const stitch = this.conversations.find(
                        c => c.conversation_type === 'simulated_feedback'
                    );
                    if (stitch) this.switchConversation(stitch.id);
                } else {
                    console.error('[ChatManager] Failed to create Stitch conversation:', resp.status);
                }
            } catch (err) {
                console.error('[ChatManager] Error creating Stitch conversation:', err);
            }
        },

        /**
         * Synchronize the form lock state with the active conversation's is_locked property.
         * Uses $dispatch to communicate with the chatFormState component reactively.
         */
        _syncFormLock() {
            const conv = this.getActiveConversation();
            const locked = conv ? conv.is_locked : this.isChatLocked;
            const conversationType = conv?.conversation_type ?? 'simulated_patient';
            this.$dispatch('conversation:lock-changed', { isLocked: locked, conversationType });
        },

        // ----- Socket / EventBus -----

        /**
         * Initialize SimulationSocket
         */
        initializeSocket() {
            // Create socket instance (from apps.simulation-socket.js)
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
            // Determine if message is from AI (incoming) or from current user (outgoing)
            const isFromSimulatedUser = data.isFromLLM ?? data.isFromAi ?? data.isFromAI ?? data.is_from_ai ?? false;
            const senderId = data.senderId ?? data.sender_id;
            const isFromSelf = !isFromSimulatedUser && (
                senderId === parseInt(this.currentUser) ||
                data.user === this.currentUser
            );
            const messageId = data.message_id ?? data.id;
            const msgConversationId = data.conversation_id ?? null;

            // If from simulated user (AI), stop typing indicator
            if (isFromSimulatedUser) {
                this.simulateSystemTyping(false);

                // Sidebar pulse for new messages
                if (localStorage.getItem('seenSidebarTray') === 'true') {
                    localStorage.removeItem('seenSidebarTray');
                    if (this.sidebarGesture) this.sidebarGesture.shouldPulse = true;
                }
            }

            // Route by conversation: if message belongs to a different conversation,
            // increment unread badge instead of rendering in the active view.
            // Use immutable update to ensure Alpine reactivity triggers.
            if (msgConversationId && msgConversationId !== this.activeConversationId) {
                this.conversations = this.conversations.map(c =>
                    c.id === msgConversationId
                        ? { ...c, _unread: (c._unread || 0) + 1 }
                        : c
                );

                // Play receive sound even for background conversation messages
                const receiveSound = document.getElementById("receive-sound");
                if (!isFromSelf && receiveSound) {
                    receiveSound.currentTime = 0;
                    receiveSound.play().catch(() => {});
                }
                return;
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

            // For AI messages, fetch server-rendered HTML via WebSocket-first pattern
            // This ensures HTML structure matches server templates
            if (isFromSimulatedUser && messageId) {
                this._fetchAndAppendMessage(messageId);
                return;
            }

            // For user's own messages (echoed back), use JS rendering for immediate feedback
            const status = isFromSelf ? data.status || 'delivered' : null;
            const displayName = data.display_name || data.displayName || data.user || 'Unknown';

            // Parse content
            let content = data.content;
            if (typeof content === 'string' && content.startsWith('"') && content.endsWith('"')) {
                try {
                    content = JSON.parse(content);
                } catch (e) {
                    console.warn("Failed to parse message content", e);
                }
            }

            this.appendMessage(
                content,
                isFromSelf,
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
                // Show error to user
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add('Failed to load message', 'error');
                } else {
                    // Fallback: append error message to chat
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700';
                    errorDiv.textContent = 'Failed to load message. Please refresh the page.';
                    this.messagesDiv.appendChild(errorDiv);
                }
            });
        },

        handleTyping(data, started) {
            if (data.user !== this.currentUser) {
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
                this.socket.send('typing', { user: this.currentUser });
                this.lastTypedTime = now;
            }

            clearTimeout(this.typingTimeout);
            this.typingTimeout = setTimeout(() => {
                this.socket.send('stopped_typing', { user: this.currentUser });
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
            if (!message) return;

            // Check active conversation lock
            const conv = this.getActiveConversation();
            if (conv?.is_locked) return;

            // Optimistic UI: show message immediately
            this.appendMessage(
                message,
                true,
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
                const body = {
                    content: message,
                    message_type: 'text',
                };
                // Include conversation_id so server routes to correct conversation
                if (this.activeConversationId) {
                    body.conversation_id = this.activeConversationId;
                }

                const response = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/messages/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                        body: JSON.stringify(body),
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

        appendMessage(content, isFromSelf, status = "", displayName = "", messageId = null, mediaList = []) {
            console.info("[ChatManager] New message!", { content, isFromSelf, status, displayName });

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
                // Use exact match on the message content element to avoid false positives
                // from substring matching against display names, timestamps, etc.
                const contentEls = this.messagesDiv.querySelectorAll('.chat-bubble .break-words');
                existing = Array.from(contentEls).find(el =>
                    el.textContent.trim() === content
                )?.closest('.chat-bubble') || null;
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
            messageDiv.className = `chat-bubble relative block w-fit max-w-[90%] rounded-2xl px-3 py-2 text-sm leading-relaxed shadow-sm sm:max-w-[75%] ${
                isFromSelf
                    ? 'outgoing ml-auto rounded-br-md bg-[var(--color-bg-outgoing)] text-[var(--color-text-light)]'
                    : 'incoming mr-auto rounded-bl-md bg-[var(--color-bg-incoming)] text-[var(--color-text-dark)]'
            }`;

            const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            const mediaHtml = this._renderMediaHtml(mediaList);

            messageDiv.innerHTML = `
                ${!isFromSelf ? `<strong class="sender-name mb-1 block text-xs font-semibold text-content-secondary">${this.escapeHtml(displayName)}</strong>` : ''}
                ${mediaHtml}
                <div class="break-words">${content}</div>
                <div class="timestamp mt-1 flex items-center justify-end gap-1 text-[10px] opacity-80 sm:text-xs">
                    <span class="bubble-time">${timestamp}</span>
                    ${isFromSelf ? this._renderStatusIcons(status) : ''}
                </div>
            `;
            return messageDiv;
        },

        _renderMediaHtml(mediaList) {
            if (!Array.isArray(mediaList) || mediaList.length === 0) return '';
            return `
                <div class="media-container mb-2 grid grid-cols-2 gap-2">
                    ${mediaList.map(media => `
                        <div class="media-wrapper overflow-hidden rounded-md border border-border">
                            <img src="${media.url}" class="media-image h-full w-full object-cover" alt="media-${media.id}">
                        </div>
                    `).join('')}
                </div>
            `;
        },

        _renderStatusIcons(status) {
            const delivered = !!status;
            const read = status === 'read';
            return `
                <span class="status-icons relative ml-1 inline-flex h-4 w-5" x-data="{ delivered: ${delivered}, read: ${read} }">
                    <span class="iconify status-icon delivered-icon absolute left-0 top-0 text-[11px] text-content-secondary" data-icon="fa6-regular:circle-check" x-show="delivered"></span>
                    <span class="iconify status-icon read-icon absolute left-1 top-0 text-[11px] text-emerald-500" data-icon="fa6-regular:circle-check" x-show="read"></span>
                </span>
            `;
        },

        _handleScrollBehavior(isSender) {
            const wasAtBottom = this.isScrolledToBottom();

            if (isSender || wasAtBottom) {
                this.messagesDiv.scrollTo({ top: this.messagesDiv.scrollHeight, behavior: 'smooth' });
            } else {
                this.newMessageBtn.classList.remove('hidden', 'animate-bounce');
                this.newMessageBtn.classList.add('animate-bounce');
                setTimeout(() => this.newMessageBtn.classList.remove('animate-bounce'), 1000);
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

        /**
         * Load the initial batch of messages for the active conversation.
         * Called after conversations are loaded (replaces hx-trigger="load" to avoid race).
         */
        loadInitialMessages() {
            if (!this.activeConversationId) {
                // No conversations yet — fall back to unfiltered load
                this.loadOlderMessages();
                return;
            }
            const url = `/chatlab/simulation/${this.simulation_id}/refresh/messages/?conversation_id=${this.activeConversationId}`;
            htmx.ajax('GET', url, { target: '#chat-messages', swap: 'innerHTML' }).then(() => {
                this.messagesDiv.scrollTop = this.messagesDiv.scrollHeight;
            });
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
                let url = `/chatlab/simulation/${this.simulation_id}/refresh/messages/older/?before=${messageId}`;
                if (this.activeConversationId) {
                    url += `&conversation_id=${this.activeConversationId}`;
                }

                // Use single HTMX request with afterSwap handler
                htmx.ajax('GET', url, {
                    target: anchor,
                    swap: 'beforebegin',
                }).then(() => {
                    // Maintain scroll position after prepending messages
                    const addedHeight = container.scrollHeight - previousHeight;
                    container.scrollTop += addedHeight;

                    // Check if more messages exist by inspecting the response
                    const newFirstMessage = container.firstElementChild;
                    if (!newFirstMessage?.dataset?.messageId || newFirstMessage === firstMessage) {
                        this.hasMoreMessages = false;
                        if (loadButton) loadButton.style.display = "none";
                    } else {
                        if (loadButton) {
                            loadButton.disabled = false;
                            loadButton.textContent = "Load Older Messages";
                        }
                    }
                }).catch(err => {
                    console.error("[ChatManager] Failed to load older messages:", err);
                    if (loadButton) {
                        loadButton.disabled = false;
                        loadButton.textContent = "Load Older Messages";
                    }
                    // Show error to user
                    if (window.Alpine?.store('toasts')) {
                        window.Alpine.store('toasts').add('Failed to load older messages', 'error');
                    }
                });
            }
        },

        updateTypingUsers(data, started = true) {
            const displayName = data.display_name || data.user || 'Someone';
            const displayInitials = data.display_initials || 'Unk';
            if (!started) {
                this.typingUsers = this.typingUsers.filter(u => u.user !== data.user);
            } else {
                const alreadyTyping = this.typingUsers.some(u => u.user === data.user);
                if (!alreadyTyping) {
                    this.typingUsers.push({ user: data.user, displayInitials });
                }
            }
            console.debug(
                '[ChatManager]',
                data.user,
                (started ? 'started' : 'stopped'), 'typing.',
                this.typingUsers.length, 'users typing:',
                JSON.stringify(this.typingUsers)
            );
        },

        simulateSystemTyping(started = true) {
            const dataSim = {
                user: 'System',
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
