# Gemini Gem Shortcut — Design Plan

## Context

A global keyboard shortcut on Ubuntu GNOME (Wayland) that opens a small, focused input dialog. After typing a prompt and pressing Enter, the dialog expands and streams a reply from the Gemini API. Each "Gem" is a named system-instruction + default-model preset, selectable from a dropdown in the dialog. A gear icon opens settings (API key, manage Gems, manage models).

Decisions locked in during planning:
- There is **no official Google API** that targets a real Gem on `gemini.google.com`. The only ways to hit a literal Gem are unofficial (reverse-engineered web RPC, browser extension intercepting `?q=`, or clipboard+keystroke automation).
- The chosen approach is the **official Gemini API** with a `system_instruction` that mimics each Gem. The default model is **`gemini-3.1-flash-lite`** (3.0 Flash-Lite does not exist; 3.1 is the GA stable model in the Flash-Lite line).
- Conversation is **multi-turn while the window is open**, **one-shot** after it closes.
- **Pure Wayland**, latest GTK (GTK4). Window positioning is left to the compositor.

## Tech stack

- **Language**: Python 3 (Ubuntu ships it).
- **UI**: GTK4 via PyGObject (`gi`). Uses `Gtk.DropDown` + `Gtk.StringList` (the non-deprecated successor to `Gtk.ComboBoxText`). Pure Wayland — no `GDK_BACKEND=x11` override. PyGObject is `apt install python3-gi gir1.2-gtk-4.0`.
- **HTTP / streaming**: `httpx` (supports server-sent events). Installed via `pip install httpx` into a venv inside the project dir, created with `--system-site-packages` so GTK stays reachable.
- **Async/UI bridge**: a worker thread runs the streaming generator and pushes tokens onto the GTK main loop with `GLib.idle_add`. Zero extra deps.
- **Keyboard shortcut**: GNOME custom keybinding via `gsettings` or the Settings GUI (documented in README — not auto-applied).

## File layout

```
~/Documents/Gemini Gem Shortcut/
├── README.md             # setup, shortcut binding, troubleshooting
├── PLAN.md               # this document
├── requirements.txt      # httpx (PyGObject is a system package)
├── main.py               # entry point, GTK App, MainWindow, SettingsWindow
├── gemini_client.py      # streaming SSE wrapper around generativelanguage API
├── config.py             # load/save ~/.config/gemini-gem-shortcut/config.json
└── run.sh                # wrapper invoked by the keyboard shortcut
```

## Config format

Path: `~/.config/gemini-gem-shortcut/config.json` (chmod 0600).

```json
{
  "api_key": "AIza...",
  "default_model": "gemini-3.1-flash-lite",
  "default_gem": "General",
  "models": [
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro",
    "gemini-3-flash-preview"
  ],
  "gems": [
    {
      "name": "General",
      "system_instruction": "",
      "default_model": null
    },
    {
      "name": "Code reviewer",
      "system_instruction": "You are a senior reviewer. Be terse. Point to file:line.",
      "default_model": "gemini-3.1-pro"
    }
  ]
}
```

`api_key` is stored plaintext with restrictive perms. Upgrading to GNOME Keyring via `libsecret` is future work.

## UI behavior

**Initial state** — compact ~640px wide window. Positioning is left to the compositor (no client-side positioning on Wayland). GTK4 dropped window-level "always-on-top" / "skip-taskbar" hints as well — those are compositor concerns now.

```
┌──────────────────────────────────────────────────┐
│ [Gem: General ▾]  [Model: 3.1 Flash-Lite ▾]  [⚙] │
│ ┌──────────────────────────────────────────────┐ │
│ │ Ask anything…                                │ │
│ └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

- Input is focused on open.
- Gem and Model dropdowns reflect last selection (or defaults from config).
- Picking a Gem updates the Model dropdown to that Gem's `default_model` if set.
- **Enter** submits. **Shift+Enter** inserts newline. **Esc** closes the window.
- **Ctrl+,** or gear icon opens settings.

**After submit** — the response frame becomes visible below the input. A scrollable `TextView` streams tokens in. Input box becomes read-only until streaming finishes, then is cleared and refocused for the next turn. Conversation history is kept in memory until the window closes.

**Settings window** — separate `Gtk.Window`, transient/modal to the main window:
- API key (password-masked `Gtk.Entry`).
- Models (one per line in a `Gtk.TextView`).
- Default model (`Gtk.Entry`).
- Gems — `Gtk.Notebook`, one tab per gem with name / system instruction / default model. Add / remove gem buttons.
- Default gem (`Gtk.Entry`).
- Save writes to config and emits a `saved` signal that the main window subscribes to in order to refresh dropdowns.

**Single instance** — implemented with `Gtk.Application` unique-name `com.iboalali.GeminiGemShortcut`. Pressing the shortcut again while the window is open just focuses the existing window (handled by `GApplication.activate`).

## Gemini client

Use the official REST endpoint with SSE:

```
POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:streamGenerateContent?alt=sse
Header: x-goog-api-key: {API_KEY}
Body: {
  "system_instruction": {"parts": [{"text": "..."}]} ,
  "contents": [
    {"role": "user", "parts": [{"text": "turn 1"}]},
    {"role": "model", "parts": [{"text": "reply 1"}]},
    {"role": "user", "parts": [{"text": "turn 2"}]}
  ]
}
```

Parse SSE lines `data: {json}`, extract `candidates[0].content.parts[0].text`, push each delta to the UI via `GLib.idle_add`. On stream end, the assembled assistant message is appended to the in-memory history so the next turn includes it as a `"role": "model"` entry.

Errors (invalid key, quota, 5xx, network) surface as `GeminiError` and render inline in the response area as an italic red line; the trailing user turn is rolled back from history so the conversation isn't poisoned.

## Keyboard shortcut wiring

Not auto-applied. README documents both:

**GUI method** (recommended):
1. *Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts → `+`*
2. **Name**: `Gemini Gem`. **Command**: absolute path to `run.sh`. **Shortcut**: e.g. `Super+Space` or `Ctrl+Alt+G`.

**CLI method**:
```bash
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
KEY=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/gemini-gem/

gsettings set $SCHEMA custom-keybindings "['$KEY']"
gsettings set "$SCHEMA.custom-keybinding:$KEY" name 'Gemini Gem'
gsettings set "$SCHEMA.custom-keybinding:$KEY" command "$HOME/Documents/Gemini Gem Shortcut/run.sh"
gsettings set "$SCHEMA.custom-keybinding:$KEY" binding '<Ctrl><Alt>g'
```

`run.sh` exec's `.venv/bin/python main.py`. Because `Gtk.Application` is single-instance, repeat presses just focus the existing window.

## Module responsibilities

- `main.py` — `Gtk.Application` + `MainWindow` (input, Gem/Model dropdowns, expanding response view, conversation state) + `SettingsWindow` (API key, models, Gems). Also hosts small `_dropdown_*` helpers that wrap `Gtk.DropDown` so the rest of the code can read/write by string.
- `gemini_client.py` — `stream_generate(api_key, model, system_instruction, contents) -> Iterator[str]` using `httpx.stream("POST", …)` and parsing SSE. Raises `GeminiError` on any failure with a human-friendly message.
- `config.py` — `load() -> dict`, `save(cfg: dict)`, default-config bootstrap, 0600 perms, plus a `find_gem(cfg, name)` helper.
- `run.sh` — venv launcher invoked by the keyboard shortcut.

## Verification

End-to-end checks:

1. **Install deps**: `sudo apt install python3-gi gir1.2-gtk-4.0 python3-venv && python3 -m venv --system-site-packages .venv && .venv/bin/pip install -r requirements.txt && chmod +x run.sh`.
2. **First launch**: `./run.sh` → window opens, input focused. Settings dialog opens via gear icon. Save API key + add at least one Gem.
3. **Single-shot**: Type "say hi" with the General Gem and `gemini-3.1-flash-lite`, press Enter → response frame appears, tokens stream in.
4. **Multi-turn**: After response, ask "what did I just say?" → model echoes "say hi", proving the history is sent.
5. **Gem switching**: Pick a Gem whose `default_model` differs from the global default → model dropdown auto-switches. Submit a prompt → reply tone reflects the system instruction.
6. **Esc closes**: window disappears, history is dropped.
7. **Shortcut binding**: bind `Ctrl+Alt+G` via README steps → press it from any app → window appears. Press again while open → existing window refocuses (single-instance via `GApplication`).
8. **Error path**: temporarily corrupt the API key in settings → submit → see inline error, history unchanged.
9. **File perms**: `ls -l ~/.config/gemini-gem-shortcut/config.json` → `-rw-------`.

## Out of scope for v1 (noted in README as future work)

- ~~Bottom-anchored window positioning.~~ **Implemented** as the optional GNOME Shell extension at `extension/gemini-gem-shortcut@iboalali.com/`. The extension runs inside Mutter and calls `MetaWindow.move_frame()` on `display::window-created`, matching the launcher by GTK app-id. Layer Shell and XWayland were considered and rejected — the Shell extension is the only path that respects the "pure Wayland + latest GTK" constraint.
- Markdown rendering of replies (would need WebKitGTK or a markdown-to-Pango converter).
- Image / file attachments (the API supports them but UI work is non-trivial).
- GNOME Keyring storage for the API key.
- Tray icon / quick-switch menu.
- Conversation persistence across window closes.
