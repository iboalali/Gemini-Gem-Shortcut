# Gemini Gem Shortcut

A small launcher window for Ubuntu GNOME that talks to the Gemini API.

- Bind a global keyboard shortcut (e.g. `Ctrl+Alt+G`).
- Press it → a focused, undecorated dark "Spotlight-style" input appears.
- Type a prompt → press `Enter` → the dialog grows and streams the reply.
- Conversation is multi-turn while the window is open. Closing the window resets it.
- A gear icon opens settings (API key, models, "Gems" = named system-instruction presets).
- Drag the window from any empty area to move it.
- *Optional:* a companion GNOME Shell extension can bottom-anchor the window
  Spotlight-style — see [Optional: bottom-anchored window position](#optional-bottom-anchored-window-position).

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
- Each Gem can also opt into **auto-pasting the clipboard** into the input
  when the window opens — toggle *"Paste clipboard into input on open"* on
  the Gem's tab. The pasted text is pre-selected, so `Enter` sends it as-is
  or your first keystroke replaces it.
- Each Gem can also opt into **auto-pasting the selected text** — toggle
  *"Paste selected text into input on open"*. This grabs whatever text you
  have **highlighted** in any other app (the primary selection / middle-click
  buffer), so you can highlight a sentence, hit the shortcut, and send it
  straight to your Gem. When both paste options are on, the selection wins
  and the clipboard is used only if nothing is highlighted. *Note:* this only
  reads **highlighted** text from apps that support the selection protocol
  (most GTK/Qt/GNOME apps, terminals, and browsers do); Wayland does not let
  any app read arbitrary, unselected text fields.
- Each Gem has a **Thinking** checkbox. On asks the model for its highest
  thinking level (better on hard questions, slower). Off asks for the lowest
  level the model allows: fully off on Flash-Lite and most Flash models, while
  some Flash models refuse to disable it and keep a little thinking. Models
  that do not support thinking levels at all are sent the request without one.
- The window auto-closes when it loses focus (spotlight-launcher behavior).
- Pressing the keyboard shortcut while the window is open just refocuses it
  (single-instance via `GApplication`).

## Token usage

Each reply is followed by its own token count, and the header shows the running
total for today. Hover the total for a per-model breakdown plus 7- and 30-day
sums.

**What the number counts:** input + output + thinking, added up over every
reply today. That is what you are billed for, and it is why a long conversation
gets expensive: the whole history is resent on every turn, so turn 5 pays for
turns 1-4 again.

**It is not your free-tier headroom.** The free tier meters *requests* and
*input* tokens, per model per day. Output and thinking tokens dominate the
total but count against no token quota, so the headline number can look alarming
while your actual quota use is tiny. The tooltip lists input tokens (`in`) and
request counts per model for exactly this reason.

The counts come from the `usageMetadata` the API returns with every response,
added up locally in `~/.config/gemini-gem-shortcut/usage.json` (chmod `0600`,
90 days of history). **This file is the only usage history you get**: the Gemini
API has no usage or quota endpoint, so nothing can be reconstructed after the
fact. Delete the file to reset the counters.

Two things it does not see: replies you cut off by closing the window mid-stream,
and any other use of the same API key. For an authoritative number, check
<https://ai.dev/rate-limit>.

## Config

`~/.config/gemini-gem-shortcut/config.json` (chmod `0600`):

```json
{
  "api_key": "AIza...",
  "default_model": "gemini-3.5-flash-lite",
  "default_gem": "General",
  "models": ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-3.1-pro-preview"],
  "gems": [
    {"name": "General", "system_instruction": "", "default_model": null, "auto_copy": false, "auto_paste_clipboard": false, "auto_paste_selection": false, "thinking": false},
    {"name": "Translator → DE", "system_instruction": "Translate to German.", "default_model": null, "auto_copy": true, "auto_paste_clipboard": false, "auto_paste_selection": true, "thinking": false}
  ]
}
```

You can edit this file directly or use the settings window.

Two things to know about the model list:

- **Updating the app does not rewrite an existing config.** Missing keys are
  filled in from the defaults, but a `models` list you already have is left
  alone — so a newer default lineup only reaches you on a fresh install. Edit
  the list in settings (or in the file) to pick up newer models.
- **Pro models require a paid tier.** On a free API key, `*-pro*` requests fail
  with `HTTP 429 … limit: 0` (a hard zero allowance, not a temporary throttle).
  The Flash and Flash-Lite entries work on the free tier. Run
  `curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=$KEY"`
  to see every model your key can address.

## Optional: bottom-anchored window position

By default the launcher opens wherever GNOME/Mutter places it (usually
centered). If you want a Spotlight-style bottom-center anchor, install
the small companion GNOME Shell extension in [`extension/`](extension/):

```bash
./extension/install.sh
# then log out and back in (Wayland)
```

See [`extension/README.md`](extension/README.md) for what it does, how
to configure the offset, and the multi-monitor behavior. The app works
without it; this is purely additive.

## Known limitations / future work

- **Window position** without the optional extension is whatever the
  GNOME compositor picks (usually centered). Pure Wayland clients can't
  position themselves; GTK4 also removed `move()`. The companion
  extension above is the supported way to get a fixed position.
- **Always-on-top / skip-taskbar** hints were dropped in GTK4 too. The window
  behaves like a regular app window.
- **API key** is stored plaintext in `~/.config/gemini-gem-shortcut/config.json`
  (file mode `0600`). Migrating to GNOME Keyring via `libsecret` is on the list.
- **Replies render as plain text.** No markdown styling yet.
- **No attachments.** Text only.
