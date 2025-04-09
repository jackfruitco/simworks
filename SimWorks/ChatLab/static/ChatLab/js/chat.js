function ChatManager(simulation_id, currentUser) {
    return {
        currentUser,
        simulation_id,
        chatSocket: null,
        messageText: '',
        typingTimeout: null,
        lastTypedTime: 0,
        typingUsers: [],
        hasMoreMessages: true,
        systemDisplayInitials: '',
        systemDisplayName: '',
        init() {
            this.messageInput = document.getElementById('chat-message-input');
            this.messageForm = document.getElementById('chat-form');
            this.messagesDiv = document.getElementById('chat-messages');
            this.metadataDiv = document.getElementById('simulation-metadata');
            this.csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            this.newMessageBtn = document.getElementById('new-message-btn');

            this.initializeWebSocket();
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
            });
        },
        notifyTyping() {
            const now = Date.now();
            if (!this.typingTimeout && now - this.lastTypedTime > 2000) {
                this.chatSocket.send(JSON.stringify({
                    type: 'typing',
                    username: this.currentUser
                }));
                this.lastTypedTime = now;
            }

            clearTimeout(this.typingTimeout);
            this.typingTimeout = setTimeout(() => {
                this.chatSocket.send(JSON.stringify({
                    type: 'stopped_typing',
                    username: this.currentUser
                }));
                this.typingTimeout = null;
            }, 1000);
        },
        initializeWebSocket() {
            const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
            const wsUrl = `${wsScheme}://${window.location.host}/ws/simulation/${this.simulation_id}/`;

            this.chatSocket = new WebSocket(wsUrl);

            this.chatSocket.onopen = () => {
                console.log('WebSocket connection established');
                this.chatSocket.send(JSON.stringify({ type: 'client_ready' }));
            };

            this.chatSocket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                console.log('[ChatManager]', data);
                if (data.type === 'init_message') {
                    // Update systemDisplayName and systemDisplayInitials only not already set to a meaningful value.
                    if (!this.systemDisplayName || this.systemDisplayName === "Unknown") {
                        this.systemDisplayName = data.sim_display_name || "Unknown";
                    }
                    if (!this.systemDisplayInitials || this.systemDisplayInitials === "Unk") {
                        this.systemDisplayInitials = data.sim_display_initials || "Unk";
                    }
                } else if (data.type === 'error') {
                    alert(data.message);
                    window.location.href = data.redirect || "/";
                } else if (data.type === 'message_status_update') {
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
                    return;
                } else if (data.type === 'typing') {
                    if (data.username !== this.currentUser) {
                        this.updateTypingUsers(data)
                    }
                } else if (data.type === 'stopped_typing') {
                    this.updateTypingUsers(data, false)
                } else if (data.type === 'chat_message' || data.type === 'message') {
                    const isSender = data.sender === this.currentUser;
                    const status = isSender ? data.status || 'delivered' : null;
                    const displayName = data.display_name || data.username || 'Unknown';
                    if (!isSender) {
                        this.simulateSystemTyping(false);
                        // trigger hx-get to update Simulation Metadata
                        fetch(`/ChatLab/simulation/${this.simulation_id}/refresh/metadata/`)
                          .then(res => {
                            const contentType = res.headers.get("content-type");
                            if (contentType && contentType.includes("application/json")) {
                              return res.json(); // JSON = no changes
                            } else {
                              return res.text(); // HTML = update needed
                            }
                          })
                          .then(data => {
                            if (typeof data === "string") {
                              this.metadataDiv.outerHTML = data;
                              this.metadataDiv = document.getElementById('simulation-metadata');
                            } else if (data.changed === false) {
                              // fallback: metadata div is empty → force refresh
                              if (!this.metadataDiv.querySelector('ul.sim-metadata')) {
                                console.warn("[metadata] Forcing fallback render...");
                                fetch(`/ChatLab/simulation/${this.simulation_id}/refresh/metadata/?force=1`)
                                  .then(res => res.text())
                                  .then(html => {
                                    this.metadataDiv.outerHTML = html;
                                    this.metadataDiv = document.getElementById('simulation-metadata');
                                  });
                              }
                            }
                          });
                    }
                    let content = data.content;
                    if (typeof content === 'string' && content.startsWith('"') && content.endsWith('"')) {
                        try {
                            content = JSON.parse(content);
                        } catch (e) {
                            console.warn("Failed to parse message content", e);
                        }
                    }
                    console.log("[appendMessage]", { content, isSender, status, displayName });
                    this.appendMessage(content, isSender, status, displayName, data.id);
                    if (this.messagesDiv.scrollHeight <= this.messagesDiv.clientHeight + 100) {
                        this.messagesDiv.scrollTop = this.messagesDiv.scrollHeight;
                    }
                    const receiveSound = document.getElementById("receive-sound");
                    if (!isSender && receiveSound) {
                        receiveSound.currentTime = 0;
                        receiveSound.play().catch(() => {});
                    }
                }
            };

            this.chatSocket.onclose = () => {
                console.log('WebSocket connection closed');
                setTimeout(() => this.initializeWebSocket(), 5000);
            };
        },
        isScrolledToBottom() {
            return this.messagesDiv.scrollHeight - this.messagesDiv.scrollTop <= this.messagesDiv.clientHeight + 50;
        },
        setupEventListeners() {
            // Removed the submit event listener
        },
        sendMessage() {
            const message = this.messageText.trim();
            if (!message) return;

            if (this.chatSocket.readyState === WebSocket.OPEN) {
                this.chatSocket.send(JSON.stringify({
                    type: 'message',
                    content: message,
                    role: 'user',
                    status: 'sent'
                }));

                this.appendMessage(
                    message,
                    true,
                    null, // no initial status
                    this.currentUser
                );

                this.messageText = '';

                const sendSound = document.getElementById("send-sound");
                if (sendSound) {
                    sendSound.currentTime = 0;
                    sendSound.play().catch(() => {});
                }
                this.simulateSystemTyping(true)
            } else {
                alert('WebSocket is not connected. Please wait and try again.');
            }
        },
        appendMessage(content, isSender, status = "", displayName = "", messageId = null) {
            if (typeof content === 'string') {
                try {
                    if (content.startsWith('"') && content.endsWith('"')) {
                        content = JSON.parse(content);
                    }
                } catch (e) {
                    console.warn("Failed to parse message content", e);
                }
            }

            status = status || "";
            content = this.escapeHtml(content);

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
                console.log("[appendMessage] Skipping duplicate message", messageId || "(no id)");
                return;
            }

            // Ensure standardized displayName for the Sim System User
            if (!isSender) { displayName = this.systemDisplayName; }

            const wasAtBottom = this.isScrolledToBottom();
            const messageDiv = document.createElement('div');
            messageDiv.className = `chat-bubble ${isSender ? 'outgoing' : 'incoming'}`;
            messageDiv.innerHTML = `
                ${!isSender ? `<strong class="sender-name">${this.escapeHtml(displayName)}</strong>` : ''}
                ${content}
                <div class="timestamp">
                    <span class="bubble-time">
                        ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
                    </span>
                    ${
                        isSender
                            ? `<span class="status-icons" x-data="{ delivered: ${!!status}, read: ${status === 'read'} }">
                                <span class="iconify status-icon delivered-icon" data-icon="fa6-regular:circle-check" data-inline="false" x-show="delivered"></span>
                                <span class="iconify status-icon read-icon" data-icon="fa6-regular:circle-check" data-inline="false" x-show="read"></span>
                            </span>`
                            : ''
                    }
                </div>
            `;

            if (messageId) {
                messageDiv.dataset.messageId = messageId;
            }

            this.messagesDiv.appendChild(messageDiv);

            if (isSender) {
                this.messagesDiv.scrollTo({
                    top: this.messagesDiv.scrollHeight,
                    behavior: 'smooth'
                });
            } else if (wasAtBottom) {
                this.messagesDiv.scrollTo({
                    top: this.messagesDiv.scrollHeight,
                    behavior: 'smooth'
                });
            } else {
                this.newMessageBtn.classList.remove('hidden');
                this.newMessageBtn.classList.add('bounce');
                setTimeout(() => {
                  this.newMessageBtn.classList.remove('bounce');
                }, 1000);
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
            const container = document.getElementById('chat-messages');
            const firstMessage = container.firstElementChild;
            const messageId = firstMessage?.dataset?.messageId || null;

            if (messageId) {
                container.setAttribute('hx-get', `/chat/${this.simulation_id}/load-older/?before=${messageId}`);
                container.setAttribute('hx-swap', 'beforebegin');
                container.setAttribute('hx-trigger', 'revealed');
                htmx.process(container);

                fetch(`/chat/${this.simulation_id}/load-older/?before=${messageId}`)
                    .then(response => response.text())
                    .then(html => {
                        if (!html.includes('data-message-id')) {
                            this.hasMoreMessages = false;
                        }
                    });
            }
        },
        updateTypingUsers (data, started=true) {
            const displayName = data.display_name || data.username || 'Someone';
            const displayInitials = data.display_initials || 'Unk';
            if (!started) {
                this.typingUsers = this.typingUsers.filter(u => u.username !== data.username);
            } else {
                const alreadyTyping = this.typingUsers.some(u => u.username === data.username);
                if (!alreadyTyping) {
                    // this.typingUsers.push({username: data.username, displayName, displayInitials});
                    this.typingUsers.push({username: data.username, displayInitials})
                }
            }
            console.log(
                '[typingUsers]',
                data.username,
                (started ? 'started' : 'stopped'), 'typing.',
                this.typingUsers.length, 'users typing:',
                JSON.stringify(this.typingUsers)
            );
        },
        simulateSystemTyping(started = true) {
            const dataSim = {};
            dataSim['username'] = 'System';
            dataSim['display_initials'] = this.systemDisplayInitials || 'Unk';
            dataSim['display_name'] = this.systemDisplayName || 'Someone';
            this.updateTypingUsers(dataSim, started);
        },
        initScrollWatcher() {
            console.log("[ChatJS] initScrollWatcher() called");
        },
    };
}

window.ChatManager = ChatManager;
