
## SimWorks / ChatLab – Project Overview

### 🔧 Project Summary
SimWorks is a Django-based web app simulating real-time military medical scenarios for U.S. Army SOF medics. It features a secure, Signal-inspired chat interface to deliver immersive, AI-powered TeleMed interactions. The platform supports live message delivery, toast notifications, dark/light themes, and mobile-first responsiveness.

---

### 📦 App Structure

#### chatlab/
- `models.py`: Simulation, Message, Prompt
- `views.py`: simulation launch, chat UI, lazy loading, search
- `templates/chatlab/`: includes `index.html`, `chat.html`, `simulation.html`, and `partials/`
- `static/chatlab/`: `chat.css`, `style.css`, `sounds/`

#### core/
- WebSocket consumer for notifications
- Toast logic (`notifications.js`), audio (`alert.wav`, `simulation_ended.wav`)
- Notification display and persistent session storage

#### SimManAI/
- OpenAI Async client to build, generate, process, and parse AI responses
- Flow: client --> gateway --> parser -> client --> (ChatConsumer)
- Includes OpenAI Token analyics to track and manage usage 

#### Frontend Technologies
- **HTMX** for partial loading and refreshes (message history, search)
- **Alpine.js** for theme toggle, auto-refresh, typing behavior
- **Custom CSS** for Signal-style chat and base branding

---

### ⚙️ Core Features
- Signal-style **real-time chat**
- OpenAI-generated AI responses with simulated delays
- Message `Delivered` + `Read` indicators
- Role-based WebSocket handling (USER vs SIM)
- WebSocket notifications with toast display and alert sounds
- **Dark/light theme** with Alpine-based toggle and persistence
- Fully mobile-responsive layout

---

### 🔌 Infrastructure & Integration
- **Django Channels** (ASGI via Daphne)
- **Redis** for Channels backing layer
- **Docker** with .env configuration for local development
- **PostgreSQL** for persistent simulation/message storage
- **Cloudflare R2** integration (for media, TTS planned)

---

### ✅ Standards & Conventions
- **WebSocket Endpoints**:
  - `/ws/sim/<simulation_id>/` (chat)
  - `/ws/notifications/` (toast system)
- **Prompt model**:
  - Staff-editable via admin or UI
  - `get_default_prompt()` ensures default exists and is linked
- **Static Assets**:
  - Chat sounds in `static/chatlab/sounds/`
  - Theme and chat styles in `base.css`, `chat.css`, `style.css`

---

### 🧪 Testing & Validation
- Unit tests for all models: `Prompt`, `Simulation`, `Message`
- Tests ensure:
  - Message ordering and OpenAI ID handling
  - Simulation completeness and timeout
  - Prompt assignment and `modified_by`/`created_by` tracking
- HTMX and WebSocket integration tested via browser + test client

---

### 🌟 Current Priorities
- Maintain Signal-style UX across chat and message flow
- Complete dark/light mode parity site-wide
- Real-time status updates (typing, delivered, read, end-state)
- Lazy loading + HTMX-driven simulation history and message panels

---

### ⚠️ Troubleshooting Protocol
When errors occur:
1. **Models/Migrations** — run `makemigrations` + `migrate` to sync schema
2. **Templates** — ensure `hx-target` IDs and `{% include %}`s match expected content
3. **WebSockets** — verify `routing.py`, `consumers.py`, and frontend scripts align
4. **HTMX Logic** — confirm `request.htmx` returns the correct partial

---