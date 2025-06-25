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

  let pendingOrders = [];

  function showOverlay() {
    console.debug("Showing Orders overlay");
    overlay.classList.add("visible");
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
  }

  function hideOverlay() {
    console.debug("Hiding Orders overlay");
    overlay.classList.remove("visible");
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
  }

  function renderOrders() {
    orderList.innerHTML = "";
    pendingOrders.forEach((order, index) => {
      const li = document.createElement("li");
      li.className = "order-item";

      const span = document.createElement("span");
      span.textContent = order;
      li.appendChild(span);

      const removeBtn = document.createElement("button");
      removeBtn.className = "remove-order";
      removeBtn.textContent = "\u2715"; // ✕
      removeBtn.addEventListener("click", () => {
        pendingOrders.splice(index, 1);
        renderOrders();
      });
      li.appendChild(removeBtn);

      orderList.appendChild(li);
    });
  }

  function stageOrderForSignature() {
    const trimmed = orderInput.value.trim();
    if (
      trimmed &&
      trimmed.length <= 30 &&
      !pendingOrders.includes(trimmed)
    ) {
      pendingOrders.push(trimmed);
      renderOrders();
      console.log("Added", trimmed, "to pending orders:", pendingOrders);
    }
    orderInput.value = "";
  }

  function showToast(message, isSuccess = true) {
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
    spinner.classList.add("active");
    try {
      const simulationId = overlay.dataset.simulationId;
      const res = await fetch(`/simulation/${simulationId}/orders/sign-orders/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "HX-Request": "true",
        },
        body: JSON.stringify({ lab_orders: pendingOrders }),
      });
      console.log("Submitting lab orders:", pendingOrders);

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Unknown error");

      showToast("Orders submitted successfully.", true);
      console.log("Lab orders successfully submitted:", data);
      pendingOrders = [];
      renderOrders();
      hideOverlay();
    } catch (err) {
      console.error("Failed to submit lab orders:", err);
      showToast(`Error: ${err.message}`, false);
    } finally {
      // spinner.classList.add("hidden");
      spinner.classList.remove("active");
    }
  }

  // Setup event listeners
  toggleButton?.addEventListener("click", showOverlay);
  overlay?.addEventListener("click", (e) => {
    if (e.target === overlay) hideOverlay();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hideOverlay();
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