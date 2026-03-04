# Jackfruit SimWorks - Button Styles

This guide documents the standardized button styles used across SimWorks. Each variant uses consistent CSS classes and theme variables defined in `button.css` and `theme.css`.

---

## 🔵 `.button.primary`

**Description**: Main action button — bold and attention-grabbing.

- **Background**: `--color-user` → `#0b93f6`
- **Text**: `--color-text-light` → `#ffffff`
- **Use for**: Submitting forms, "Save", "Search", or initiating key actions.

---

## 🌿 `.button.secondary`

**Description**: Secondary option — supportive, but less dominant.

- **Background**: `--jckfrt-olive` → `#4B5D43`
- **Text**: `--color-text-light` → `#ffffff`
- **Use for**: Alternative actions like "Start Sim", "Back", "More Info".

---

## 💬 `.button.sim`

**Description**: Styled for simulation UIs — subtle and soft.

- **Background**: `--color-sim` → `#F1F0F0`
- **Text**: `--color-text-light` → `#ffffff`
- **Use for**: Buttons inside chat/sim components or neutral sim options.

---

## 🧊 `.button.ghost`

**Description**: Low emphasis, neutral appearance.

- **Background**: `--color-border` → `#dddddd`
- **Text**: `--color-text-dark` → `#222222`
- **Use for**: "Clear Filters", "Cancel", or secondary actions in toolbars.

---

## ✨ `.button.accent`

**Description**: Eye-catching and brand-forward — for special use cases.

- **Background**: `--jckfrt-yellow` → `#D2A640`
- **Text**: `--jckfrt-olive` → `#4B5D43`
- **Use for**: Account/profile buttons, badges, callouts.

---

## 📝 Notes

- All buttons share base styles: rounded corners, smooth hover transitions, bold font, consistent padding.
- Use `.button.small`, `.button.medium`, `.button.large` to control size responsively.
- Avoid applying inline styles — use classes to maintain theme consistency and dark mode support.