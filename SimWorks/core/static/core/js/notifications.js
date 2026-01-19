const PERSISTED_TOASTS_KEY = "persisted_toasts";

const getPersistedToasts = () =>
  JSON.parse(sessionStorage.getItem(PERSISTED_TOASTS_KEY) || "[]");

const savePersistedToasts = (toasts) =>
  sessionStorage.setItem(PERSISTED_TOASTS_KEY, JSON.stringify(toasts));

const removePersistedToast = (message) => {
  if (!message) return;
  const updated = getPersistedToasts().filter((toast) => toast.message !== message);
  savePersistedToasts(updated);
};

document.addEventListener("alpine:init", () => {
  Alpine.data("toastController", (message, extraTags = "", duration = 5000) => ({
    show: true,
    duration,
    extraTags,
    message,
    timeoutId: null,
    get persistent() {
      return (this.extraTags || "").includes("persistent");
    },
    init() {
      if (!this.persistent) {
        this.startTimer();
      }
    },
    startTimer() {
      this.clearTimer();
      this.timeoutId = setTimeout(() => this.dismiss(), this.duration);
    },
    clearTimer() {
      if (this.timeoutId) {
        clearTimeout(this.timeoutId);
        this.timeoutId = null;
      }
    },
    dismiss() {
      this.clearTimer();
      this.show = false;
      removePersistedToast(this.message);
    },
  }));
});

/**
 * NotificationSocket - WebSocket connection manager for user notifications
 *
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Deduplication of notifications
 * - Persistence across page navigation (within 5s window)
 */
class NotificationSocket {
  constructor() {
    this.socket = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10;
    this.baseDelay = 1000;
    this.maxDelay = 30000;
    this.reconnectTimeoutId = null;
    this.isIntentionallyClosed = false;
  }

  connect() {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return;
    }

    const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${wsScheme}://${window.location.host}/ws/notifications/`;

    try {
      this.socket = new WebSocket(wsUrl);
      this.socket.onopen = () => this.handleOpen();
      this.socket.onmessage = (event) => this.handleMessage(event);
      this.socket.onclose = (event) => this.handleClose(event);
      this.socket.onerror = (error) => this.handleError(error);
    } catch (error) {
      console.error('[NotificationSocket] Failed to create WebSocket:', error);
      this.scheduleReconnect();
    }
  }

  handleOpen() {
    console.debug('[NotificationSocket] Connected');
    this.reconnectAttempts = 0;
  }

  handleMessage(event) {
    try {
      const data = JSON.parse(event.data);
      if (data.notification) {
        const toastData = {
          message: data.notification,
          timestamp: Date.now(),
          type: data.type || "info"
        };

        const stored = getPersistedToasts();
        if (!stored.find(n => n.message === data.notification)) {
          stored.push(toastData);
          savePersistedToasts(stored);
          showToast(toastData);
        }
      }
    } catch (error) {
      console.error('[NotificationSocket] Failed to parse message:', error);
    }
  }

  handleClose(event) {
    if (this.isIntentionallyClosed) {
      console.debug('[NotificationSocket] Connection closed intentionally');
      return;
    }

    console.warn('[NotificationSocket] Connection closed:', event.code, event.reason);
    this.scheduleReconnect();
  }

  handleError(error) {
    console.error('[NotificationSocket] WebSocket error:', error);
  }

  scheduleReconnect() {
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[NotificationSocket] Max reconnection attempts reached');
      return;
    }

    const delay = Math.min(
      this.baseDelay * Math.pow(2, this.reconnectAttempts),
      this.maxDelay
    );

    console.debug(`[NotificationSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimeoutId = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  close() {
    this.isIntentionallyClosed = true;
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
    }
    if (this.socket) {
      this.socket.close();
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // Restore persisted toasts from previous page
  const persisted = getPersistedToasts();
  const now = Date.now();
  const valid = [];

  persisted.forEach(({ message, timestamp }) => {
    if (now - timestamp < 5000) {
      showToast({ message, type: "info" });
      valid.push({ message, timestamp });
    }
  });
  savePersistedToasts(valid);

  // Initialize WebSocket with reconnection support
  const notificationSocket = new NotificationSocket();
  notificationSocket.connect();

  // Expose for debugging
  window._notificationSocket = notificationSocket;
});

function showToast({ message, type }) {
  const containerId = "notifications-container";
  let container = document.getElementById(containerId);

  if (!container) {
    container = document.createElement("div");
    container.id = containerId;
    container.className = "fixed top-0 right-0 m-4 space-y-2";
    document.body.appendChild(container);
  }

  // Play sound based on type
  let soundId = "alert-sound";
  if (type === "simulation-ended" || message.toLowerCase().includes("simulation ended")) {
    soundId = "simulation-ended-sound";
  }
  const sound = document.getElementById(soundId);
  if (sound) {
    sound.currentTime = 0;
    sound.play().catch(() => {});
  }

  const toast = document.createElement("div");
  toast.className = "toast flex items-center justify-between info";
  toast.setAttribute("role", "status");
  toast.setAttribute("aria-live", "assertive");

  const text = document.createElement("span");
  text.textContent = message;

  const close = document.createElement("button");
  close.innerHTML = "&times;";
  close.className = "dismiss";
  close.setAttribute("aria-label", "Dismiss");
  close.onclick = () => {
    removePersistedToast(message);
    toast.remove();
  };

  toast.appendChild(text);
  toast.appendChild(close);
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("hide");
    setTimeout(() => toast.remove(), 300);
  }, 5000);
}
