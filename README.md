# Gemini Gem Shortcut

A small launcher window for Ubuntu GNOME that talks to the Gemini API.

- Bind a global keyboard shortcut (e.g. `Ctrl+Alt+G`).
- Press it → a focused, undecorated dark "Spotlight-style" input appears.
- Type a prompt → press `Enter` → the dialog grows and streams the reply.
- Conversation is multi-turn while the window is open. Closing the window resets it.
- A gear icon opens settings (API key, models, "Gems" = named system-instruction presets).
- Drag the window from any empty area to move it.

<img width="1302" height="308" alt="image" src="https://github.com/user-attachments/assets/11005d36-dc6b-4b75-9d30-31f01ad2dd5a" />

<img width="1304" height="1880" alt="image" src="https://github.com/user-attachments/assets/0bb7c7fa-3ed6-4269-abc5-e5090c85501e" />


## Why "Gems" are mimicked, not real

There is no official Google API that targets a real custom Gem on
`gemini.google.com`. This app uses the official Gemini API and applies your
Gem's instructions via the `system_instruction` field. The persona is the
same; the conversation isn't visible in your Gemini web history.

## Setup

```bash
# Run these from the project directory.

# 1. System dependencies (GTK4 + PyGObject)
sudo apt install python3-gi gir1.2-gtk-4.0 python3-venv

# 2. Project venv with access to system PyGObject
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt

# 3. Make the launcher executable
chmod +x run.sh

# 4. Launch once to create the config and add your API key
./run.sh
# Click the ⚙ gear icon → paste your API key → Save
```

Get an API key from <https://aistudio.google.com/apikey>.

## Bind a keyboard shortcut

### GUI (recommended)

1. *Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts → `+`*
2. **Name**: `Gemini Gem`
3. **Command**: `"/path/to/Gemini Gem Shortcut/run.sh"`
   - Use the absolute path — GNOME does **not** expand `~` in this field.
   - Wrap it in double quotes because the path contains spaces.
4. **Shortcut**: pick e.g. `Ctrl+Alt+G`

### CLI

```bash
# Run this from the project directory so $(pwd) resolves correctly.
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
KEY=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/gemini-gem/

gsettings set $SCHEMA custom-keybindings "['$KEY']"
gsettings set "$SCHEMA.custom-keybinding:$KEY" name 'Gemini Gem'
gsettings set "$SCHEMA.custom-keybinding:$KEY" command "$(pwd)/run.sh"
gsettings set "$SCHEMA.custom-keybinding:$KEY" binding '<Ctrl><Alt>g'
```

## Usage

- `Enter` — submit the prompt
- `Shift+Enter` — newline in the input
- `Esc` — close the window (drops the conversation)
- `Ctrl+,` or click `⚙` — open settings
- `Ctrl+C` — copy the current selection in the response area to the clipboard.
  Select text with the mouse first.
- Each Gem can opt into **automatic copy-to-clipboard** of every full
  response — toggle *"Copy response to clipboard automatically"* on the
  Gem's tab in settings.
- The window auto-closes when it loses focus (spotlight-launcher behavior).
- Pressing the keyboard shortcut while the window is open just refocuses it
  (single-instance via `GApplication`).

## Config

`~/.config/gemini-gem-shortcut/config.json` (chmod `0600`):

```json
{
  "api_key": "AIza...",
  "default_model": "gemini-3.1-flash-lite",
  "default_gem": "General",
  "models": ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.1-pro-preview"],
  "gems": [
    {"name": "General", "system_instruction": "", "default_model": null, "auto_copy": false},
    {"name": "Translator → DE", "system_instruction": "Translate to German.", "default_model": null, "auto_copy": true}
  ]
}
```

You can edit this file directly or use the settings window.

## Known limitations / future work

- **Window position** is whatever the GNOME compositor picks (usually centered).
  Pure Wayland clients can't position themselves; GTK4 also removed `move()`.
  If you really want bottom-centered, the options are (a) GTK Layer Shell
  (requires a wlroots compositor — won't work on stock GNOME/Mutter) or
  (b) launching under XWayland with `GDK_BACKEND=x11`. Out of scope for v1.
- **Always-on-top / skip-taskbar** hints were dropped in GTK4 too. The window
  behaves like a regular app window.
- **API key** is stored plaintext in `~/.config/gemini-gem-shortcut/config.json`
  (file mode `0600`). Migrating to GNOME Keyring via `libsecret` is on the list.
- **Replies render as plain text.** No markdown styling yet.
- **No attachments.** Text only.
