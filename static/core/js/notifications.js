document.addEventListener("DOMContentLoaded", () => {
  const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${wsScheme}://${window.location.host}/ws/notifications/`;

  const notificationSocket = new WebSocket(wsUrl);

  const persisted = JSON.parse(sessionStorage.getItem("persisted_toasts") || "[]");
  const now = Date.now();
  const valid = [];

  persisted.forEach(({ message, timestamp }) => {
    if (now - timestamp < 5000) {
      showToast({ message, type: "info" }); // Default type for persisted toasts
      valid.push({ message, timestamp });
    }
  });
  sessionStorage.setItem("persisted_toasts", JSON.stringify(valid));

  notificationSocket.onmessage = function(event) {
    const data = JSON.parse(event.data);
    if (data.notification) {
      const toastData = {
        message: data.notification,
        timestamp: Date.now(),
        type: data.type || "info"
      };

      const stored = JSON.parse(sessionStorage.getItem("persisted_toasts") || "[]");
      if (!stored.find(n => n.message === data.notification)) {
          stored.push(toastData);
          sessionStorage.setItem("persisted_toasts", JSON.stringify(stored));
          showToast(toastData);
      }
    }
  };
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
    const updated = JSON.parse(sessionStorage.getItem("persisted_toasts") || "[]").filter(n => n.message !== message);
    sessionStorage.setItem("persisted_toasts", JSON.stringify(updated));
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
