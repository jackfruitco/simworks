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
function ChatManager(simulation_id, currentUserId, currentUserEmail) {
    return {
        currentUserId: Number.parseInt(currentUserId, 10),
        currentUserEmail,
        simulation_id,
        socket: null,
        eventBus: null,
        toolManager: null,
        messageText: '',
        typingTimeout: null,
        lastTypedTime: 0,
        typingUsersByConversation: {},
        hasMoreMessages: true,
        isMessagesLoading: false,
        isOlderLoading: false,
        systemDisplayInitials: '',
        systemDisplayName: '',
        isChatLocked: false,
        conversationCache: {},
        pendingClientMessages: new Map(),
        clientMessageSeq: 0,
        seenMessageIds: new Set(),
        seenMessageOrder: [],
        maxSeenMessageIds: 1000,
        isAtMessagesTop: false,
        olderLoadFailed: false,
        socketDisconnected: false,
        simulationFailureBanner: {
            show: false,
            text: '',
            code: '',
            retryable: true,
        },
        feedbackFailureBanner: {
            show: false,
            text: '',
            code: '',
            retryable: true,
        },
        fallbackPollIntervalId: null,

        // --- Multi-conversation state ---
        conversations: [],
        activeConversationId: null,

        get activeTypingUsers() {
            if (!this.activeConversationId) return [];
            const users = this.typingUsersByConversation[this.activeConversationId] || [];
            return users.filter(user => !this._isSelfTypingPayload(user));
        },

        init() {
            this.messageInput = document.getElementById('chat-message-input');
            this.messageForm = document.getElementById('chat-form');
            this.messagesDiv = document.getElementById('chat-messages');
            this.messagesPanel = document.getElementById('chat-messages-panel');
            this.simMetadataDiv = document.getElementById('simulation_metadata_tool');
            this.patientMetadataDiv = document.getElementById('patient_history_tool');
            this.csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            this.newMessageBtn = document.getElementById('new-message-btn');

            // Get DOM data attributes
            const simulationContext = document.getElementById('context');
            this.isChatLocked = simulationContext?.dataset.isChatLocked === 'true';
            const initialStatus = simulationContext?.dataset.simulationStatus || 'in_progress';
            const reasonCode = simulationContext?.dataset.simulationTerminalReasonCode || '';
            const reasonText = simulationContext?.dataset.simulationTerminalReasonText || '';
            const retryable = simulationContext?.dataset.simulationRetryable !== 'false';
            if (initialStatus === 'failed') {
                this.simulationFailureBanner = {
                    show: true,
                    text: reasonText || 'Initial patient generation failed. Please try again.',
                    code: reasonCode,
                    retryable,
                };
            }

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
                this._updateScrollState();
                if (this.isScrolledToBottom()) {
                    this.newMessageBtn.classList.add('hidden');
                    this.newMessageBtn.classList.remove('animate-bounce');
                }
                if (this._shouldAutoLoadOlder()) {
                    this.loadOlderMessages();
                }
            });

            this._updateScrollState();
        },

        _setMessagesLoading(loading) {
            this.isMessagesLoading = loading;
        },

        _setOlderLoading(loading) {
            this.isOlderLoading = loading;
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
                    id: this._normalizeConversationId(c.id),
                    _unread: 0,
                }));

                // Default to first conversation (patient) if none active
                if (this.conversations.length && !this.activeConversationId) {
                    this.activeConversationId = this._normalizeConversationId(this.conversations[0].id);
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
            const activeConversationId = this._normalizeConversationId(this.activeConversationId);
            return this.conversations.find(c => c.id === activeConversationId) || null;
        },

        /**
         * Switch the visible conversation. Reloads messages for the target conversation.
         */
        switchConversation(convId) {
            const nextConversationId = this._normalizeConversationId(convId);
            if (!nextConversationId || nextConversationId === this.activeConversationId) return;

            const previousConversationId = this.activeConversationId;
            if (previousConversationId) {
                this._cacheConversationHtml(previousConversationId);
                this._clearSystemTyping(previousConversationId);
            }

            this.activeConversationId = nextConversationId;
            this.hasMoreMessages = true;
            this.olderLoadFailed = false;
            this.newMessageBtn?.classList.add('hidden');

            // Reset unread badge for this conversation
            this.conversations = this.conversations.map(c =>
                c.id === nextConversationId
                    ? { ...c, _unread: 0 }
                    : c
            );

            // Sync form lock state
            this._syncFormLock();

            const restoredFromCache = this._restoreConversationFromCache(nextConversationId);
            if (!restoredFromCache) {
                this._fetchConversationMessages(nextConversationId, { scrollToBottom: true, force: true });
                return;
            }

            this.messagesDiv.scrollTop = this.messagesDiv.scrollHeight;
            this._updateScrollState();
            this._checkConversationFreshness(nextConversationId);
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
                onResyncRequired: () => window.location.reload(),
            });
        },

        /**
         * Initialize EventBus and subscribe to chat-related events
         */
        initializeEventBus() {
            this.eventBus = new SimulationEventBus();
            this.eventBus.attachSocket(this.socket);

            // Subscribe to chat UI events only
            this.eventBus.on('session.ready', (data) => this.handleSessionReady(data));
            this.eventBus.on('session.resumed', (data) => this.handleSessionReady(data));
            this.eventBus.on('session.resync_required', (data) => this.handleSessionResyncRequired(data));
            this.eventBus.on('message.item.created', (data) => this.handleChatMessage(data));
            this.eventBus.on('typing.started', (data) => this.handleTyping(data, true));
            this.eventBus.on('typing.stopped', (data) => this.handleTyping(data, false));
            this.eventBus.on('message.delivery.updated', (data) => this.handleMessageStatusUpdate(data));
            this.eventBus.on('error', (data) => this.handleError(data));
            this.eventBus.on('connected', () => this.handleSocketConnected());
            this.eventBus.on('disconnected', () => this.handleSocketDisconnected());
            this.eventBus.on('simulation.status.updated', (data) => this.handleSimulationStateChanged(data));
            this.eventBus.on('assessment.generation.failed', (data) => this.handleFeedbackFailed(data));
            this.eventBus.on('assessment.generation.updated', (data) => this.handleFeedbackRetrying(data));
        },

        /**
         * Initialize ToolManager with declarative tool configuration
         */
        initializeToolManager() {
            this.toolManager = new ToolManager(this.simulation_id, this.eventBus);

            // Declarative tool configuration - tools auto-refresh on events
            this.toolManager.configure({
                'patient_history': {
                    refreshOn: ['message.item.created'],
                    refreshMode: 'checksum',
                },
                'simulation_metadata': {
                    refreshOn: ['message.item.created'],
                    refreshMode: 'checksum',
                },
                'simulation_assessment': {
                    refreshOn: ['assessment.item.created'],
                    refreshMode: 'html_inject',
                },
                'patient_results': {
                    refreshOn: ['patient.results.updated'],
                    refreshMode: 'html_inject',
                },
            });

            // Auto-discover any additional tools not explicitly configured
            this.toolManager.autoDiscover();
        },

        handleSessionReady(data) {
            if (!this.systemDisplayName || this.systemDisplayName === "Unknown") {
                this.systemDisplayName = data.patient_display_name || "Unknown";
            }
            if (!this.systemDisplayInitials || this.systemDisplayInitials === "Unk") {
                this.systemDisplayInitials = data.patient_initials || "Unk";
            }
        },

        handleSessionResyncRequired(_data) {
            window.location.reload();
        },

        handleChatMessage(data) {
            // Determine if message is from AI (incoming) or from current user (outgoing)
            const isFromSimulatedUser = data.is_from_ai ?? false;
            const senderId = data.sender_id;
            const messageIdRaw = data.message_id ?? data.id;
            const messageIdParsed = Number.parseInt(messageIdRaw, 10);
            const messageId = Number.isFinite(messageIdParsed) ? messageIdParsed : null;
            const msgConversationId = this._normalizeConversationId(
                data.conversation_id ?? this.activeConversationId
            );
            const activeConversationId = this._normalizeConversationId(this.activeConversationId);
            const senderIdNum = Number.parseInt(senderId, 10);
            const senderEmail = data.user ?? data.sender_email ?? null;
            const isFromSelf = !isFromSimulatedUser && (
                (Number.isFinite(senderIdNum) && senderIdNum === this.currentUserId) ||
                (!!senderEmail && !!this.currentUserEmail && senderEmail === this.currentUserEmail)
            );

            if (messageId && this._hasSeenMessage(messageId)) {
                console.debug("[ChatManager] Skipping seen message event", messageId);
                return;
            }
            if (messageId) {
                this._rememberSeenMessage(messageId);
            }

            // If from simulated user (AI), stop typing indicator
            if (isFromSimulatedUser) {
                this.simulateSystemTyping(false, msgConversationId || activeConversationId);

                // Sidebar pulse for new messages
                if (localStorage.getItem('seenSidebarTray') === 'true') {
                    localStorage.removeItem('seenSidebarTray');
                    if (this.sidebarGesture) this.sidebarGesture.shouldPulse = true;
                }
            }

            // Route by conversation: if message belongs to a different conversation,
            // increment unread badge instead of rendering in the active view.
            // Use immutable update to ensure Alpine reactivity triggers.
            if (msgConversationId && msgConversationId !== activeConversationId) {
                if (!isFromSelf) {
                    this.conversations = this.conversations.map(c =>
                        c.id === msgConversationId
                            ? { ...c, _unread: (c._unread || 0) + 1 }
                            : c
                    );
                }
                this._markConversationDirty(msgConversationId);

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

            if (isFromSelf && messageId && this._reconcilePendingMessageByEcho(data.content, messageId, msgConversationId)) {
                this._cacheConversationHtml(msgConversationId, { dirty: false });
                return;
            }

            // Deduplication check
            if (messageId && this._messageExists(messageId)) {
                console.debug("[ChatManager] Skipping duplicate message", messageId);
                return;
            }

            // For AI messages, fetch server-rendered HTML via WebSocket-first pattern
            // This ensures HTML structure matches server templates
            if (isFromSimulatedUser && messageId) {
                this._fetchAndAppendMessage(messageId, msgConversationId || activeConversationId);
                return;
            }

            // For user's own messages (echoed back), use JS rendering for immediate feedback
            const status = isFromSelf
                ? (data.delivery_status || data.status || 'sent')
                : null;
            const displayName = data.display_name || data.user || 'Unknown';

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
                data.media_list ?? []
            );
            this._cacheConversationHtml(msgConversationId || activeConversationId, { dirty: false });
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
        _fetchAndAppendMessage(messageId, conversationId = this.activeConversationId) {
            const url = `/chatlab/simulation/${this.simulation_id}/message/${messageId}/`;
            const wasAtBottomBeforeAppend = this.isScrolledToBottom();

            htmx.ajax('GET', url, {
                target: '#chat-messages',
                swap: 'beforeend',
            }).then(() => {
                this._handleScrollBehavior(false, wasAtBottomBeforeAppend);
                this._cacheConversationHtml(conversationId, { dirty: false });
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

        _isSelfTypingPayload(data) {
            if (!data) return false;

            const senderIdRaw = data.sender_id ?? data.actor_user_id ?? data.senderId ?? data.actorUserId;
            const senderId = Number.parseInt(senderIdRaw, 10);

            if (
                Number.isFinite(senderId) &&
                Number.isFinite(this.currentUserId) &&
                senderId === this.currentUserId
            ) {
                return true;
            }

            const payloadUser = data.user ? String(data.user).toLowerCase() : '';
            const currentEmail = this.currentUserEmail ? String(this.currentUserEmail).toLowerCase() : '';

            if (payloadUser && currentEmail && payloadUser === currentEmail) {
                return true;
            }

            return false;
        },

        handleTyping(data, started) {
            if (this._isSelfTypingPayload(data)) {
                this.removeTypingUser(data);
                return;
            }

            this.updateTypingUsers(data, started);
        },

        handleSocketConnected() {
            this.socketDisconnected = false;
            if (this.fallbackPollIntervalId) {
                clearInterval(this.fallbackPollIntervalId);
                this.fallbackPollIntervalId = null;
            }
        },

        handleSocketDisconnected() {
            this.socketDisconnected = true;
            if (this.fallbackPollIntervalId) return;
            this.fallbackPollIntervalId = setInterval(() => {
                if (!this.activeConversationId) return;
                this._checkConversationFreshness(this.activeConversationId);
            }, 5000);
        },

        handleSimulationStateChanged(data) {
            if (data.status === 'failed') {
                this.simulationFailureBanner = {
                    show: true,
                    text: data.terminal_reason_text || 'Simulation failed. Please try again.',
                    code: data.terminal_reason_code || '',
                    retryable: data.retryable !== false,
                };
                this.simulateSystemTyping(false);
                return;
            }

            if (data.status === 'in_progress') {
                this.simulationFailureBanner.show = false;
            }
        },

        handleFeedbackFailed(data) {
            this.feedbackFailureBanner = {
                show: true,
                text: data.error_text || 'Feedback generation failed.',
                code: data.error_code || '',
                retryable: data.retryable !== false,
            };
        },

        handleFeedbackRetrying(_data) {
            this.feedbackFailureBanner.show = false;
        },

        handleMessageStatusUpdate(data) {
            const existing = this.messagesDiv.querySelector(`[data-message-id="${data.id}"]`);
            if (existing) {
                const statusIcons = existing.querySelector('.status-icons');
                if (statusIcons) {
                    this._setStatusIcons(statusIcons, data.status);
                }
                if (data.error_text) {
                    existing.dataset.deliveryError = data.error_text;
                } else {
                    delete existing.dataset.deliveryError;
                }
                this._syncRetryButton(existing, data);
            }
        },

        handleError(data) {
            console.error('[ChatManager] Realtime error', data);
            if (data.code === 'access_denied') {
                alert(data.message || 'ChatLab access denied.');
                window.location.href = '/chatlab/';
                return;
            }
            if (window.Alpine?.store('toasts')) {
                window.Alpine.store('toasts').add(data.message || 'Realtime error', 'error');
            }
        },

        notifyTyping() {
            const now = Date.now();
            if (!this.typingTimeout && now - this.lastTypedTime > 2000) {
                this.socket.send('typing.started', {
                    conversation_id: this.activeConversationId,
                });
                this.lastTypedTime = now;
            }

            clearTimeout(this.typingTimeout);
            this.typingTimeout = setTimeout(() => {
                this.socket.send('typing.stopped', {
                    conversation_id: this.activeConversationId,
                });
                this.typingTimeout = null;
            }, 1000);
        },

        isScrolledToBottom() {
            return this.messagesDiv.scrollHeight - this.messagesDiv.scrollTop <= this.messagesDiv.clientHeight + 50;
        },

        setupEventListeners() {
            this.messagesDiv.addEventListener('click', (event) => {
                const retryButton = event.target.closest('.js-retry-message');
                if (!retryButton) return;

                const bubble = retryButton.closest('.chat-bubble');
                if (!bubble) return;

                const messageId = bubble.dataset.messageId;
                const retryDraft = bubble.dataset.retryDraft || '';

                if (messageId) {
                    this.retryMessage(messageId);
                    return;
                }

                // Local transport failure before persistence: resend draft content.
                if (retryDraft) {
                    for (const [key, pending] of this.pendingClientMessages.entries()) {
                        if (pending.bubble === bubble) {
                            this.pendingClientMessages.delete(key);
                            break;
                        }
                    }
                    bubble.remove();
                    this.messageText = retryDraft;
                    this.sendMessage();
                }
            });
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

            const optimisticKey = `client-${Date.now()}-${++this.clientMessageSeq}`;
            // Optimistic UI: show message immediately
            const optimisticBubble = this.appendMessage(
                message,
                true,
                'sending',
                this.currentUserEmail,
                null,
                [],
                optimisticKey,
            );
            if (optimisticBubble) {
                this.pendingClientMessages.set(optimisticKey, {
                    bubble: optimisticBubble,
                    content: message,
                    conversationId: this.activeConversationId,
                });
                this._cacheConversationHtml(this.activeConversationId, { dirty: false });
            }

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

                const responseData = await response.json().catch(() => ({}));
                const serverMessageId = responseData?.id ?? responseData?.message_id ?? null;
                if (serverMessageId) {
                    this._reconcilePendingMessage(optimisticKey, serverMessageId, 'sent');
                }

                // 202 Accepted - AI response will arrive via WebSocket
                console.debug('[ChatManager] Message sent via API, awaiting AI response via WebSocket');
            } catch (error) {
                console.error('[ChatManager] Failed to send message:', error);
                this.simulateSystemTyping(false);
                const pending = this.pendingClientMessages.get(optimisticKey);
                if (pending?.bubble) {
                    this._updateBubbleStatus(pending.bubble, 'failed', {
                        retryable: true,
                        errorText: error.message,
                        retryDraft: pending.content,
                    });
                }
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add(`Failed to send message: ${error.message}`, 'error');
                }
            }
        },

        /**
         * Handle form:send event dispatched from chatFormState
         */
        async handleFormSend(detail) {
            this.messageText = detail.messageText;
            await this.sendMessage();
        },

        async retryMessage(messageId) {
            const existing = this.messagesDiv.querySelector(`[data-message-id="${messageId}"]`);
            if (existing) {
                this._updateBubbleStatus(existing, 'sending');
            }

            try {
                const response = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/messages/${messageId}/retry/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                    }
                );

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${response.status}`);
                }

                if (existing) {
                    this._updateBubbleStatus(existing, 'sent');
                }
                this.simulateSystemTyping(true);
            } catch (error) {
                if (existing) {
                    this._updateBubbleStatus(existing, 'failed', {
                        retryable: true,
                        errorText: error.message,
                    });
                }
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add(`Retry failed: ${error.message}`, 'error');
                }
            }
        },

        async retryInitialSimulation() {
            try {
                const response = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/retry-initial/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                    }
                );
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${response.status}`);
                }

                this.simulationFailureBanner.show = false;
                this.simulateSystemTyping(true);
            } catch (error) {
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add(`Retry failed: ${error.message}`, 'error');
                }
            }
        },

        async retryFeedback() {
            try {
                const response = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/retry-feedback/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                    }
                );
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${response.status}`);
                }
                this.feedbackFailureBanner.show = false;
            } catch (error) {
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add(`Feedback retry failed: ${error.message}`, 'error');
                }
            }
        },

        appendMessage(
            content,
            isFromSelf,
            status = "",
            displayName = "",
            messageId = null,
            mediaItems = [],
            clientMessageId = null,
        ) {
            console.info("[ChatManager] New message!", { content, isFromSelf, status, displayName });

            content = this._coerceContent(content);
            status = status || "";

            if (this._isDuplicateMessage(messageId, clientMessageId)) return null;

            if (!isFromSelf && displayName === "") {
                displayName = this.systemDisplayName;
            }

            const wasAtBottomBeforeAppend = this.isScrolledToBottom();
            const bubble = this._buildMessageBubble(
                content,
                isFromSelf,
                displayName,
                status,
                mediaItems,
            );
            if (messageId) bubble.dataset.messageId = messageId;
            if (clientMessageId) bubble.dataset.clientMessageId = clientMessageId;

            this.messagesDiv.appendChild(bubble);
            this._handleScrollBehavior(isFromSelf, wasAtBottomBeforeAppend);
            return bubble;
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

        _isDuplicateMessage(messageId, clientMessageId) {
            if (messageId && this._messageExists(messageId)) {
                console.debug("[ChatManager] Skipping duplicate message", messageId);
                return true;
            }
            if (
                clientMessageId &&
                this.messagesDiv.querySelector(`[data-client-message-id="${clientMessageId}"]`)
            ) {
                console.debug("[ChatManager] Skipping duplicate optimistic message", clientMessageId);
                return true;
            }
            return false;
        },

        _buildMessageBubble(content, isFromSelf, displayName, status, mediaItems) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `chat-bubble relative block w-fit max-w-[90%] rounded-2xl px-3 py-2 text-sm leading-relaxed shadow-sm sm:max-w-[75%] ${
                isFromSelf
                    ? 'outgoing ml-auto rounded-br-md bg-[var(--color-bg-outgoing)] text-[var(--color-text-light)]'
                    : 'incoming mr-auto rounded-bl-md bg-[var(--color-bg-incoming)] text-[var(--color-text-dark)]'
            }`;

            const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            const mediaHtml = this._renderMediaHtml(mediaItems);
            const retryButton = isFromSelf && status === 'failed'
                ? '<button type="button" class="js-retry-message ml-1 rounded border border-red-300 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 hover:bg-red-100">Try again</button>'
                : '';

            messageDiv.innerHTML = `
                ${!isFromSelf ? `<strong class="sender-name mb-1 block text-xs font-semibold text-content-secondary">${this.escapeHtml(displayName)}</strong>` : ''}
                ${mediaHtml}
                <div class="break-words">${content}</div>
                <div class="timestamp mt-1 flex items-center justify-end gap-1 text-[10px] opacity-80 sm:text-xs">
                    <span class="bubble-time">${timestamp}</span>
                    ${isFromSelf ? this._renderStatusIcons(status) : ''}
                    ${retryButton}
                </div>
            `;
            return messageDiv;
        },

        _renderMediaHtml(mediaItems) {
            if (!Array.isArray(mediaItems) || mediaItems.length === 0) return '';
            return `
                <div class="media-container mb-2 grid grid-cols-2 gap-2">
                    ${mediaItems.map(media => `
                        <div class="media-wrapper overflow-hidden rounded-md border border-border">
                            <img src="${media.thumbnail_url || media.original_url}" class="media-image h-full w-full object-cover" alt="media-${media.id}">
                        </div>
                    `).join('')}
                </div>
            `;
        },

        _renderStatusIcons(status) {
            const normalizedStatus = this._normalizeDeliveryStatus(status);
            return `
                <span class="status-icons relative ml-1 inline-flex h-4 w-5" data-status="${normalizedStatus}">
                    <span class="iconify status-icon sending-icon absolute left-0 top-0 text-[11px] text-content-secondary ${normalizedStatus === 'sending' ? '' : 'hidden'}" data-icon="svg-spinners:3-dots-scale"></span>
                    <span class="iconify status-icon sent-icon absolute left-0 top-0 text-[11px] text-content-secondary ${normalizedStatus === 'sent' ? '' : 'hidden'}" data-icon="fa6-regular:circle-check"></span>
                    <span class="iconify status-icon delivered-icon absolute left-0 top-0 text-[11px] text-content-secondary ${normalizedStatus === 'delivered' ? '' : 'hidden'}" data-icon="fa6-solid:check-double"></span>

                    <!--<span class="iconify status-icon failed-icon absolute left-0 top-0 text-[11px] text-red-500 ${normalizedStatus === 'failed' ? '' : 'hidden'}" data-icon="fa6-solid:triangle-exclamation"></span> -->
                </span>
            `;
        },

        _normalizeDeliveryStatus(status) {
            // return ['sending', 'sent', 'delivered', 'failed'].includes(status) ? status : 'sent';
            // Temporary hotfix: suppress failed indicator in UI until backend status
            // transitions are fully corrected in a follow-up release.
            if (status === 'failed') return 'delivered';
            return ['sending', 'sent', 'delivered'].includes(status) ? status : 'sent';
        },

        _setStatusIcons(statusIcons, status) {
            if (!statusIcons) return;
            const normalizedStatus = this._normalizeDeliveryStatus(status);
            statusIcons.dataset.status = normalizedStatus;

            const iconByStatus = {
                sending: statusIcons.querySelector('.sending-icon'),
                sent: statusIcons.querySelector('.sent-icon'),
                delivered: statusIcons.querySelector('.delivered-icon'),
                // failed: statusIcons.querySelector('.failed-icon'),
            };

            Object.entries(iconByStatus).forEach(([name, el]) => {
                if (!el) return;
                el.classList.toggle('hidden', name !== normalizedStatus);
            });
        },

        _updateBubbleStatus(bubble, status, options = {}) {
            if (!bubble) return;

            const statusIcons = bubble.querySelector('.status-icons');
            if (statusIcons) {
                this._setStatusIcons(statusIcons, status);
            }

            if (options.errorText) {
                bubble.dataset.deliveryError = options.errorText;
            } else {
                delete bubble.dataset.deliveryError;
            }

            if (status === 'failed' && options.retryDraft) {
                bubble.dataset.retryDraft = options.retryDraft;
            }

            this._syncRetryButton(bubble, {
                status,
                retryable: options.retryable !== false,
            });
        },

        _syncRetryButton(bubble, data = {}) {
            // const status = data.status || bubble.querySelector('.status-icons')?.dataset?.status;
            const rawStatus = data.status || bubble.querySelector('.status-icons')?.dataset?.status;
            const status = this._normalizeDeliveryStatus(rawStatus);
            const retryable = data.retryable !== false;
            let retryButton = bubble.querySelector('.js-retry-message');

            if (status === 'failed' && retryable) {
                if (!retryButton) {
                    const ts = bubble.querySelector('.timestamp');
                    retryButton = document.createElement('button');
                    retryButton.type = 'button';
                    retryButton.className = 'js-retry-message ml-1 rounded border border-red-300 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 hover:bg-red-100';
                    retryButton.textContent = 'Try again';
                    ts?.appendChild(retryButton);
                }
                return;
            }

            if (retryButton) {
                retryButton.remove();
            }
        },

        _handleScrollBehavior(isSender, wasAtBottomBeforeAppend = false) {
            if (isSender || wasAtBottomBeforeAppend) {
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
                return;
            }
            this._fetchConversationMessages(this.activeConversationId, {
                scrollToBottom: true,
                force: true,
            });
        },

        loadOlderMessages() {
            const activeConversationId = this._normalizeConversationId(this.activeConversationId);
            if (this.isOlderLoading || this.isMessagesLoading || !activeConversationId) {
                return;
            }

            const container = document.getElementById('chat-messages');
            const firstMessage = container.querySelector('.chat-bubble[data-message-id]');
            const messageId = firstMessage?.dataset?.messageId || null;
            this._setOlderLoading(true);

            if (!messageId) {
                this.hasMoreMessages = false;
                this.olderLoadFailed = false;
                this._cacheConversationHtml(activeConversationId, { hasMore: false, dirty: false });
                this._setOlderLoading(false);
                this._updateScrollState();
                return;
            }

            let anchor = document.getElementById('message-load-anchor');
            if (!anchor) {
                anchor = document.createElement('div');
                anchor.id = 'message-load-anchor';
                container.prepend(anchor);
            }

            const previousHeight = container.scrollHeight;
            let url = `/chatlab/simulation/${this.simulation_id}/refresh/messages/older/?before=${messageId}`;
            if (activeConversationId) {
                url += `&conversation_id=${activeConversationId}`;
            }

            htmx.ajax('GET', url, {
                target: anchor,
                swap: 'beforebegin',
            }).then(() => {
                const addedHeight = container.scrollHeight - previousHeight;
                container.scrollTop += addedHeight;

                const newFirstMessage = container.querySelector('.chat-bubble[data-message-id]');
                this.hasMoreMessages = !!newFirstMessage?.dataset?.messageId &&
                    newFirstMessage.dataset.messageId !== messageId;
                this.olderLoadFailed = false;
                this._cacheConversationHtml(activeConversationId, {
                    hasMore: this.hasMoreMessages,
                    dirty: false,
                });
            }).catch(err => {
                console.error("[ChatManager] Failed to load older messages:", err);
                this.olderLoadFailed = true;
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add('Failed to load older messages', 'error');
                }
            }).finally(() => {
                this._setOlderLoading(false);
                this._updateScrollState();
            });
        },

        _typingUserKey(userData) {
            return (
                userData?.actor_user_uuid ||
                userData?.actorUserUuid ||
                userData?.actor_user_id ||
                userData?.actorUserId ||
                userData?.sender_id ||
                userData?.senderId ||
                userData?.user ||
                null
            );
        },

        removeTypingUser(data) {
            const conversationId = this._normalizeConversationId(
                data?.conversation_id ?? this.activeConversationId
            );
            if (!conversationId) return;

            const targetKey = this._typingUserKey(data);
            if (!targetKey) return;

            const existingUsers = this.typingUsersByConversation[conversationId] || [];
            const nextUsers = existingUsers.filter(
                user => this._typingUserKey(user) !== targetKey
            );

            const nextByConversation = { ...this.typingUsersByConversation };
            if (nextUsers.length) {
                nextByConversation[conversationId] = nextUsers;
            } else {
                delete nextByConversation[conversationId];
            }

            this.typingUsersByConversation = nextByConversation;
        },

        updateTypingUsers(data, started = true) {
            const conversationId = this._normalizeConversationId(
                data.conversation_id ?? this.activeConversationId
            );
            if (!conversationId) return;

            const typingUser = {
                user: data.user,
                displayInitials: data.display_initials || data.displayInitials || 'Unk',
                senderId: data.sender_id ?? data.actor_user_id ?? null,
                actorUserId: data.actor_user_id ?? data.sender_id ?? null,
                actorUserUuid: data.actor_user_uuid ?? null,
                actorType: data.actor_type ?? 'user',
            };
            const typingKey = this._typingUserKey(typingUser);
            const existingUsers = this.typingUsersByConversation[conversationId] || [];
            let nextUsers = existingUsers;

            if (!started) {
                nextUsers = existingUsers.filter(u => this._typingUserKey(u) !== typingKey);
            } else {
                const existingIndex = existingUsers.findIndex(u => this._typingUserKey(u) === typingKey);
                if (existingIndex >= 0) {
                    nextUsers = [...existingUsers];
                    nextUsers[existingIndex] = { ...nextUsers[existingIndex], ...typingUser };
                } else {
                    nextUsers = [...existingUsers, typingUser];
                }
            }

            this.typingUsersByConversation = {
                ...this.typingUsersByConversation,
                [conversationId]: nextUsers,
            };

            if (!nextUsers.length) {
                delete this.typingUsersByConversation[conversationId];
            }

            console.debug(
                '[ChatManager]',
                data.user,
                (started ? 'started' : 'stopped'), 'typing.',
                nextUsers.length, 'users typing:',
                JSON.stringify(nextUsers)
            );
        },

        simulateSystemTyping(started = true, conversationId = this.activeConversationId) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId) return;
            const dataSim = {
                user: 'System',
                display_initials: this.systemDisplayInitials || 'Unk',
                display_name: this.systemDisplayName || 'Someone',
                conversation_id: normalizedConversationId,
            };
            this.updateTypingUsers(dataSim, started);
        },

        _clearSystemTyping(conversationId) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId) return;
            const users = this.typingUsersByConversation[normalizedConversationId] || [];
            const nextUsers = users.filter(u => u.user !== 'System');
            this.typingUsersByConversation = {
                ...this.typingUsersByConversation,
                [normalizedConversationId]: nextUsers,
            };
            if (!nextUsers.length) {
                delete this.typingUsersByConversation[normalizedConversationId];
            }
        },

        _markConversationDirty(conversationId) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId) return;
            const cache = this.conversationCache[normalizedConversationId];
            if (!cache) return;
            cache.dirty = true;
        },

        _getLastMessageIdFromDom() {
            const messageBubbles = this.messagesDiv.querySelectorAll('.chat-bubble[data-message-id]');
            const last = messageBubbles[messageBubbles.length - 1];
            if (!last) return null;
            const id = Number.parseInt(last.dataset.messageId, 10);
            return Number.isFinite(id) ? id : null;
        },

        _cacheConversationHtml(conversationId, overrides = {}) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId || !this.messagesDiv) return;
            const current = this.conversationCache[normalizedConversationId] || {};
            const defaultHasMore = current.hasMore ?? this.hasMoreMessages;
            this.conversationCache[normalizedConversationId] = {
                html: this.messagesDiv.innerHTML,
                lastMessageId: this._getLastMessageIdFromDom(),
                hasMore: defaultHasMore,
                dirty: current.dirty || false,
                fetchedAt: Date.now(),
                ...overrides,
            };
        },

        _restoreConversationFromCache(conversationId) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId) return false;
            const cache = this.conversationCache[normalizedConversationId];
            if (!cache?.html) return false;
            this.messagesDiv.innerHTML = cache.html;
            this.hasMoreMessages = cache.hasMore !== false;
            this.olderLoadFailed = false;
            return true;
        },

        _fetchConversationMessages(conversationId, { scrollToBottom = false, force = false } = {}) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId) return;
            if (this.isMessagesLoading && !force) return;

            this._setMessagesLoading(true);
            this.hasMoreMessages = true;
            this.olderLoadFailed = false;
            const url = `/chatlab/simulation/${this.simulation_id}/refresh/messages/?conversation_id=${normalizedConversationId}`;
            htmx.ajax('GET', url, { target: '#chat-messages', swap: 'innerHTML' }).then(() => {
                if (scrollToBottom) {
                    this.messagesDiv.scrollTop = this.messagesDiv.scrollHeight;
                    this.newMessageBtn?.classList.add('hidden');
                }
                this._cacheConversationHtml(normalizedConversationId, {
                    dirty: false,
                    hasMore: true,
                });
                this._updateScrollState();
            }).catch((err) => {
                console.error('[ChatManager] Failed to load messages:', err);
                if (window.Alpine?.store('toasts')) {
                    window.Alpine.store('toasts').add('Failed to load messages', 'error');
                }
            }).finally(() => {
                this._setMessagesLoading(false);
                this._updateScrollState();
            });
        },

        async _checkConversationFreshness(conversationId) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId) return;
            const cache = this.conversationCache[normalizedConversationId];
            if (!cache) return;

            try {
                const resp = await fetch(
                    `/api/v1/simulations/${this.simulation_id}/messages/?conversation_id=${normalizedConversationId}&order=desc&limit=1`,
                    { headers: { 'X-CSRFToken': this.csrfToken } },
                );
                if (!resp.ok) return;
                const data = await resp.json();
                const latestId = data?.items?.[0]?.id ?? null;
                const shouldRefresh = cache.dirty || (latestId && latestId !== cache.lastMessageId);
                if (shouldRefresh) {
                    this._fetchConversationMessages(normalizedConversationId, { force: true });
                } else {
                    cache.fetchedAt = Date.now();
                }
            } catch (err) {
                console.warn('[ChatManager] Freshness check failed:', err);
            }
        },

        _reconcilePendingMessage(clientKey, serverMessageId, status = 'sent') {
            const pending = this.pendingClientMessages.get(clientKey);
            if (!pending?.bubble || !serverMessageId) return;
            pending.bubble.dataset.messageId = serverMessageId;
            delete pending.bubble.dataset.clientMessageId;
            delete pending.bubble.dataset.retryDraft;
            this._updateBubbleStatus(pending.bubble, status, { retryable: true });
            this.pendingClientMessages.delete(clientKey);
            this._rememberSeenMessage(Number.parseInt(serverMessageId, 10));
            this._cacheConversationHtml(pending.conversationId, { dirty: false });
        },

        _normalizeContentForCompare(content) {
            if (typeof content !== 'string') return '';
            let normalized = content;
            if (normalized.startsWith('"') && normalized.endsWith('"')) {
                try {
                    normalized = JSON.parse(normalized);
                } catch (e) {
                    // Keep original string when parse fails.
                }
            }
            return String(normalized).trim();
        },

        _reconcilePendingMessageByEcho(content, messageId, conversationId) {
            const normalizedConversationId = this._normalizeConversationId(conversationId);
            if (!normalizedConversationId) return false;
            const normalizedEcho = this._normalizeContentForCompare(content);
            for (const [key, pending] of this.pendingClientMessages.entries()) {
                if (pending.conversationId !== normalizedConversationId) continue;
                if (normalizedEcho && normalizedEcho !== pending.content.trim()) continue;
                if (!pending.bubble?.isConnected) {
                    this.pendingClientMessages.delete(key);
                    continue;
                }
                pending.bubble.dataset.messageId = messageId;
                delete pending.bubble.dataset.clientMessageId;
                delete pending.bubble.dataset.retryDraft;
                this._updateBubbleStatus(pending.bubble, 'sent', { retryable: true });
                this.pendingClientMessages.delete(key);
                return true;
            }
            return false;
        },

        _normalizeConversationId(value) {
            const parsed = Number.parseInt(value, 10);
            return Number.isFinite(parsed) ? parsed : null;
        },

        _updateScrollState() {
            if (!this.messagesDiv) return;
            this.isAtMessagesTop = this.messagesDiv.scrollTop <= 3;
        },

        _shouldAutoLoadOlder() {
            return (
                this.isAtMessagesTop &&
                this.hasMoreMessages &&
                !this.olderLoadFailed &&
                !this.isMessagesLoading &&
                !this.isOlderLoading
            );
        },

        _hasSeenMessage(messageId) {
            return this.seenMessageIds.has(messageId);
        },

        _rememberSeenMessage(messageId) {
            if (!Number.isFinite(messageId)) return;
            if (this.seenMessageIds.has(messageId)) return;
            this.seenMessageIds.add(messageId);
            this.seenMessageOrder.push(messageId);

            if (this.seenMessageOrder.length > this.maxSeenMessageIds) {
                const expired = this.seenMessageOrder.shift();
                if (expired !== undefined) {
                    this.seenMessageIds.delete(expired);
                }
            }
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
