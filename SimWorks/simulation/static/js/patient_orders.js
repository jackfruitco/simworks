// static/js/patient_orders.js

(function () {
  const overlay = document.getElementById("order-request-form");
  const toggleButton = document.getElementById("toggle-order-request-form");
  const orderInput = document.getElementById("lab-order-input");
  const stageOrderBtn = document.getElementById("stage-order-btn");
  const orderList = document.getElementById("staged-orders-list");
  const signOrderBtn = document.getElementById("sign-orders-btn");
  const spinner = document.getElementById("orders-spinner");
  const toastContainer = document.getElementById("toast-container");
  const closeButtons = overlay?.querySelectorAll("[data-modal-close]");
  const modalBackdrop = overlay?.querySelector("[data-modal-backdrop]");

  if (!overlay) return;

  let pendingOrders = [];
  let lastFocusedElement = null;

  const focusableSelector = [
    "a[href]",
    "area[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(", ");

  function isFocusable(element) {
    if (!element) return false;
    return (
      !element.hasAttribute("data-focus-guard") &&
      element.tabIndex !== -1 &&
      !element.disabled &&
      element.getAttribute("aria-hidden") !== "true"
    );
  }

  function getFocusableElements() {
    return Array.from(overlay.querySelectorAll(focusableSelector)).filter(
      (el) => isFocusable(el) && el.offsetParent !== null,
    );
  }

  function focusInitialElement() {
    const initial = overlay.querySelector("[data-modal-initial-focus]");
    const focusable = getFocusableElements();
    const target = (isFocusable(initial) && initial) || focusable[0];
    target?.focus({ preventScroll: true });
  }

  function trapFocus(event) {
    if (event.key !== "Tab") return;

    const focusable = getFocusableElements();
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onOverlayKeydown(event) {
    if (event.key === "Escape") {
      hideOverlay();
    } else {
      trapFocus(event);
    }
  }

  function showOverlay() {
    console.debug("Showing Orders overlay");
    lastFocusedElement = document.activeElement;
    overlay.classList.add("visible");
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    overlay.addEventListener("keydown", onOverlayKeydown);
    focusInitialElement();
  }

  function hideOverlay() {
    console.debug("Hiding Orders overlay");
    overlay.classList.remove("visible");
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
    overlay.removeEventListener("keydown", onOverlayKeydown);
    if (lastFocusedElement instanceof HTMLElement) {
      lastFocusedElement.focus({ preventScroll: true });
    }
  }

  function renderOrders() {
    if (!orderList) return;
    orderList.innerHTML = "";
    pendingOrders.forEach((order, index) => {
      const li = document.createElement("li");
      li.className = "staged-item";

      const removeBtn = document.createElement("button");
      removeBtn.className = "remove-order";
      removeBtn.textContent = "\u2715"; // ✕
      removeBtn.addEventListener("click", () => {
        pendingOrders.splice(index, 1);
        renderOrders();
      });
      li.appendChild(removeBtn);

      const span = document.createElement("span");
      span.textContent = order;
      li.appendChild(span);

      orderList.appendChild(li);
    });
  }

  function stageOrderForSignature() {
    if (!orderInput) return;

    const trimmed = orderInput.value.trim();
    if (
      trimmed &&
      trimmed.length <= 30 &&
      !pendingOrders.includes(trimmed)
    ) {
      pendingOrders.push(trimmed);
      renderOrders();
      console.debug("Added", trimmed, "to pending orders:", pendingOrders);
    }
    orderInput.value = "";
  }

  function showToast(message, isSuccess = true) {
    if (!toastContainer) return;
    const toast = document.createElement("div");
    toast.className = `toast ${isSuccess ? "toast-success" : "toast-error"}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  async function signOrders() {
    if (pendingOrders.length === 0) {
      showToast("No orders staged for signature.", false);
      return;
    }
    spinner?.classList.add("active");
    spinner?.setAttribute("aria-hidden", "false");
    try {
      const simulationId = overlay.dataset.simulationId;
      const res = await fetch(`/simulation/${simulationId}/orders/sign-orders/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "HX-Request": "true",
        },
        body: JSON.stringify({ submitted_orders: pendingOrders }),
      });
      console.debug("Submitting orders:", pendingOrders);

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Unknown error");

      showToast("Orders signed.", true);
      console.info("[Orders] Success! Orders successfully submitted:", data);
      pendingOrders = [];
      renderOrders();
      hideOverlay();
    } catch (err) {
      console.error("Failed to submit orders:", err);
      showToast(`Error: ${err.message}`, false);
    } finally {
      spinner?.classList.remove("active");
      spinner?.setAttribute("aria-hidden", "true");
    }
  }

  // Setup event listeners
  toggleButton?.addEventListener("click", showOverlay);
  closeButtons?.forEach((btn) => btn.addEventListener("click", hideOverlay));
  overlay?.addEventListener("click", (e) => {
    const isBackdrop = e.target === overlay || e.target === modalBackdrop;
    if (isBackdrop) hideOverlay();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.getAttribute("aria-hidden") === "false") {
      hideOverlay();
    }
  });
  stageOrderBtn?.addEventListener("click", stageOrderForSignature);
  orderInput?.addEventListener("keyup", (e) => {
    if (e.key === "Enter") stageOrderForSignature();
  });
  signOrderBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    signOrders();
  });
})();
