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

## App icon in the dash

Install the launcher entry and icon so GNOME shows the app's icon in the dash and in Activities:

```bash
./data/install.sh
```

It writes `~/.local/share/applications/com.iboalali.GeminiGemShortcut.desktop`, pointing at this checkout's `run.sh`, and `~/.local/share/icons/hicolor/scalable/apps/com.iboalali.GeminiGemShortcut.svg`. Re-run it after moving the project folder. No logout is needed.

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

## Command line

`gemini-gem` sends one prompt without opening a window and streams the reply to stdout. Each call is a single turn with no conversation history. It has three modes, chosen by the first argument.

### Install the `gemini-gem` command

Link `cli.sh` into `~/.local/bin`, from the project directory:

```bash
ln -sfn "$(pwd)/cli.sh" ~/.local/bin/gemini-gem
gemini-gem --version   # prints "gemini-gem 0.2.0"
```

The link points at this checkout, so `git pull` updates the command, and moving the project folder needs the `ln` again. `cli.sh` finds the project's `.venv` through the link, so the command works from any directory. On Ubuntu, `~/.profile` puts `~/.local/bin` on `PATH` at login if the folder existed then. If `command -v gemini-gem` prints nothing, log out and in once. The examples below use `gemini-gem`; `./cli.sh` from the project directory works the same.

For another program, run `gemini-gem` by name, or the absolute path of `cli.sh` if `~/.local/bin` might not be on its `PATH` (a desktop launcher, a systemd unit).

### Gem mode

Uses the Gems and models from the app's config, like the window does.

```bash
gemini-gem "What is the capital of Australia?"
gemini-gem -g "Gramatik Gem" "their going too the store"
gemini-gem -m gemini-3.8-flash --thinking "Plan a 3-day trip to Lisbon"

# No prompt argument: the whole prompt comes from stdin
wl-paste | gemini-gem -g "Gramatik Gem"

# "-" inserts stdin at that spot in the prompt
cat notes.txt | gemini-gem "Summarize these notes:" -

gemini-gem --list-gems
gemini-gem --list-models   # the models in the config, not the API's list
gemini-gem --usage
```

- `-g`, `--gem NAME`: the Gem to use. Default: the config's `default_gem`.
- `-m`, `--model ID`: the model. Default: the Gem's default model, the same one the window would pick. Any model ID works here, not only the ones in `models`.
- `--thinking` / `--no-thinking`: override the Gem's Thinking checkbox.

To send a prompt that starts with `ask` or `models` in this mode, put `--` first: `gemini-gem -- models of the solar system`.

### `ask`: plain Gemini API call

Only the API key comes from the config. No Gem, default model or other setting applies. The arguments are the model, the system instruction and the question, in that order:

```bash
gemini-gem ask gemini-3.8-flash "You are a terse Linux expert." "How do I list open ports?"
gemini-gem ask gemini-3.5-flash-lite "" "No system instruction: pass an empty string"
git diff | gemini-gem ask gemini-3.8-flash "You review code." "Review this diff:" -

# System instruction from a file: the SYSTEM argument is left out
wl-paste | gemini-gem ask --no-thinking --system-file ~/proofread.txt gemini-3.5-flash-lite -
```

`-s`, `--system-file FILE` reads the system instruction from a UTF-8 file instead. That keeps a long instruction off the command line and out of `ps`, and its text is never mistaken for an option. Passed as an argument, a system instruction that starts with `-` needs `--` before the model: `gemini-gem ask -- gemini-3.8-flash "-x" "question"`.

The question's words are joined with spaces, and `-` reads stdin, as in Gem mode. Without `--thinking` / `--no-thinking`, the model uses its own default thinking level.

### `models`: what the API key can use

```bash
gemini-gem models            # one model ID per line
gemini-gem models --long     # plus display name and input/output token limits
gemini-gem models --json     # the API's full model entries
gemini-gem models --refresh  # skip the cache
```

It lists every model the key can call `generateContent` on, which is what `ask` uses. Embedding-only models are left out. The answer is cached for 24 h in `~/.cache/gemini-gem-shortcut/models.json`. The cache stores a hash of the API key, not the key, and a different key fetches a fresh list. When the API can't be reached, the CLI shows the last cached list with a warning. Being listed doesn't mean a model works on your plan: on a free key, some listed models fail with `HTTP 429 … limit: 0` (see [Known limitations](#known-limitations--future-work)).

### Options and behavior for Gem mode and `ask`

- `-c`, `--copy`: also copy the full reply to the clipboard with `wl-copy`.
- `-v`, `--verbose`: print the model (and Gem) and the reply's token count to stderr.
- `--json`: print one JSON object instead of streaming text. See below.
- `-t`, `--timeout SECONDS`: give up when the reply is not complete after SECONDS, counted from the start of the request, and exit with 124. Without it, the only limits are 10 s to connect and 60 s without any data, so a long reply can run for minutes.

`gemini-gem --version` prints `gemini-gem 0.2.0` and exits 0. It makes no network call and reads no config, so it is a cheap check that the CLI and its venv work.

Stdin is read only when there is no prompt argument or an argument is `-`, so a script whose stdin never closes does not hang. While waiting for the first token, a status line ("connecting…", "waiting for the model…") appears on stderr when stderr is a terminal. Tokens are added to the same daily usage totals as the window, including those of a reply cut off by Ctrl+C or the timeout.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | The reply is complete |
| 1 | Any other failure: API error, missing or rejected key, unknown model, rate limit, empty reply, unreadable system file |
| 2 | Usage error: missing argument, unknown option, bad `--timeout` value |
| 124 | `--timeout` ran out |
| 130 | Ctrl+C |

Errors are printed to stderr as `error: <message>`. A message from Google can span several lines, as a 429 does.

#### JSON output

With `--json`, nothing is streamed. When the call ends, stdout gets exactly one JSON object on one line, for success and for every failure with exit code 1 or 124:

```json
{"ok": true, "model": "gemini-3.5-flash-lite", "text": "The quick brown fox", "usage": {"promptTokenCount": 21, "candidatesTokenCount": 5, "totalTokenCount": 26}, "error": null}
{"ok": false, "model": "gemini-4-argon", "text": "", "usage": null, "error": {"message": "HTTP 429: You exceeded your current quota…", "reason": "not on your plan", "status": 429}}
```

- `text`: the reply. On a failure, the part that arrived before it, often `""`.
- `usage`: the API's `usageMetadata` for the reply, or `null` when none arrived.
- `error.reason`: a short phrase, for example `model overloaded`, `rate limit reached, retry in 14h18m24s`, `not on your plan`, `API key rejected`, `model not found`, `timed out`, `empty reply`, `no API key`.
- `error.status`: the HTTP status when Google answered with an error, otherwise `null`.

The `error:` line still goes to stderr as well. Usage errors (exit 2) and Ctrl+C print no JSON.


*Note on `--copy`:* GNOME does not support the Wayland protocol that lets a background tool set the clipboard. `wl-copy` works around that by opening a 1×1 window and waiting for focus, and GNOME does not focus it when it is started from a script. The reply is still printed, `--copy` then prints a warning after 5 s and the exit code stays 0.

## Request status, Retry and Cancel

A status row at the bottom of the window shows what the current request is doing, with a colored dot and a seconds counter:

- **Connecting:** opening the connection to Google. If no connection is made within 10 s, the request fails with "can't reach Google".
- **Waiting for the model:** the request was sent and the model has not started answering. Some models take 20 s or more before the first word, and nothing comes back over the network until then. After 60 s of silence the request fails with "no answer from the model".
- **Streaming:** the reply is arriving.
- **Done in X s**, **Canceled after X s** or **Failed after X s: reason.** The reason is a short summary such as "model overloaded", "rate limit reached, retry in 14h18m24s", "not on your plan" or "API key rejected". The full error message appears in the response area.

The **Retry** and **Cancel** buttons are always shown, and each is only clickable when it applies:

- **Cancel** works while a request is running. The partial reply stays on screen, marked "(canceled)", and the prompt is dropped from the conversation.
- **Retry** works after a failure, an empty reply or a cancel. It sends the last prompt again with the Gem and model selected *at the time you click*, so you can switch away from an overloaded model first. Text you have typed in the input in the meantime is kept.

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
and any other use of the same API key. A canceled reply is counted only up to the point where you canceled it. For an authoritative number, check
<https://ai.dev/rate-limit>.

## Config

`~/.config/gemini-gem-shortcut/config.json` (chmod `0600`):

```json
{
  "api_key": "AIza...",
  "default_model": "gemini-3.5-flash-lite",
  "default_gem": "General",
  "models": ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon"],
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
- **Some models require a paid tier.** On a free API key, `*-pro*`, `gemini-4-argon` and `gemini-4-carbon` requests fail with `HTTP 429 … limit: 0` (a hard zero allowance, not a temporary throttle). The Flash, Flash-Lite and `gemini-4-hydrogen` entries work on the free tier. Run `curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=$KEY"` to see every model your key can address.

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
