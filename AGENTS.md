# AGENTS.md

Guidance for coding agents working in this repository. `README.md` is the user-facing setup; this file holds the design constraints and the non-obvious behavior behind them.

## Project shape

A GTK4 launcher window for Ubuntu GNOME (Wayland) that streams replies from the official Google Gemini API.

- `main.py`: `Gtk.Application` (single-instance via app-id `com.iboalali.GeminiGemShortcut`), `MainWindow` (input, Gem and model `Gtk.DropDown`s, expanding response area, status row, multi-turn conversation) and `SettingsWindow` (API key, models, one notebook tab per Gem).
- `gemini_client.py`: `stream_generate()`, a generator that POSTs to `…/v1beta/models/{MODEL}:streamGenerateContent?alt=sse` and yields text deltas. Every failure is raised as `GeminiError` with a readable message and a short `reason`.
- `config.py`: load/save `~/.config/gemini-gem-shortcut/config.json` (mode 0600), default bootstrap, `find_gem()`.
- `usage.py`: local token accounting in `~/.config/gemini-gem-shortcut/usage.json` (mode 0600), bucketed by day and model, pruned to `RETENTION_DAYS`. Also owns the display formatting (`format_tokens`, `format_response`, `summary`) so `main.py` stays UI-only.
- `run.sh`: what the GNOME keyboard shortcut binds to. `exec`s `.venv/bin/python main.py`.
- `style.css`: dark Spotlight-style theme, loaded once by `GeminiGemApp._load_css` at `STYLE_PROVIDER_PRIORITY_APPLICATION`. Relaunch to see edits.
- `extension/gemini-gem-shortcut@iboalali.com/`: optional GNOME Shell extension (GJS, GNOME 45+ ESM) that bottom-anchors the window. The Python app knows nothing about it. See `extension/README.md` and `extension/install.sh`.

## Run and verify

```bash
# System deps (one-time)
sudo apt install python3-gi gir1.2-gtk-4.0 python3-venv

# The venv MUST use --system-site-packages so PyGObject (gi) is importable
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt

./run.sh

# Import smoke test: catches syntax and GTK4 API mistakes without a window
.venv/bin/python -c "import config, gemini_client, main; print('ok')"

# GUI smoke test: window shows for 2 s, exits 0 if clean
timeout --preserve-status 2 ./run.sh
```

There is no test suite and no linter config. The two smoke tests are the verification path.

## Locked-in constraints (do not change without asking)

- **Pure Wayland and GTK4.** No `GDK_BACKEND=x11`, no GTK3.
- **No client-side window positioning.** GTK4 has no `move()`, and Mutter does not let Wayland clients place themselves. Positioning lives only in the GNOME Shell extension, which runs inside Mutter and uses `MetaWindow.move_frame()`. No XWayland fallback, no layer-shell.
- **No deprecated widgets.** `Gtk.DropDown` + `Gtk.StringList`, not `Gtk.ComboBoxText`.
- **No always-on-top or skip-taskbar.** GTK4 has neither. The window is a normal window; don't fake these with hacks.
- **Gems are mimicked, not real.** Google has no API for the Gems on gemini.google.com. A Gem here is a `system_instruction` preset injected into a normal `generateContent` call. No reverse-engineered web RPC and no clipboard+ydotool tricks without the user's explicit go-ahead.

## Window lifecycle and focus

**The window auto-closes when focus leaves it** (Spotlight-style). Four details keep that from firing by accident:

1. It uses `Gtk.EventControllerFocus` on the window, not `notify::is-active`. The latter fires when a `Gtk.DropDown` opens its popover, which would close the window on every dropdown click.
2. `leave` schedules a deferred close (200 ms) and `enter` cancels it. When a dropdown popover closes, focus is orphaned for a moment before it returns, and the delay absorbs that.
3. The settings window is a separate toplevel, so opening it fires `leave`. `_open_settings` sets `_settings_open`, which suppresses the close; the settings window's `close-request` clears it.
4. An interactive move on Wayland (`xdg_toplevel_move`) grabs pointer and keyboard, so the window goes inactive and fires `leave` exactly like a click outside. A move always starts with a button press on this window, so a CAPTURE-phase `Gtk.GestureClick` (`_on_window_press`) records `_last_press_time`, and `_on_focus_leave` uses a 5 s delay instead of 200 ms when a press happened in the last second. CAPTURE is required because the body-level `Gtk.WindowHandle` wrapping `outer` claims the press otherwise. Neither `notify::is-active` (point 1) nor an `is_active()` check at close time can tell a move from a click outside: the move makes the window inactive too.

**Never make the focused widget insensitive or hidden.** GTK then moves focus away, `contains_focus` briefly goes false, and the deferred close fires. Lock the input with `set_editable(False)`, not `set_sensitive(False)`. Retry and Cancel toggle sensitivity, so both are `set_focusable(False)` and `set_focus_on_click(False)`.

**`_on_close_request` must stop every GLib source, drop `self.app.window`, and call `self.app.quit()`.** A pending `GLib.timeout_add` source holds a strong ref to the window, which keeps the C widget alive past destroy. The application's hold count then never reaches 0, `app.run()` never returns, and a zombie process is left behind on every shortcut press. The sources are the deferred-close timer (`_close_timeout_id`) and the status ticker (`_status_timer_id`). Any new timer must be removed here too. Keep all three steps.

**Rounded corners need a transparent toplevel.** `MainWindow` is undecorated, and the rounded dark fill is painted on the body-level `Gtk.WindowHandle`. The `window.spotlight-window` rule in `style.css` makes the toplevel `background-color: transparent`, otherwise the compositor paints an opaque rectangle behind the `border-radius`. The `.spotlight-window` class scopes this to the main window so `SettingsWindow` keeps its native chrome. A second Spotlight-style toplevel needs the same class. If the main window becomes decorated again, drop the class and the rule together.

## Requests

**Threading.** The GTK main loop owns every widget. `_send` starts a daemon thread (`_worker`) that iterates `stream_generate(...)` and posts each delta back through `GLib.idle_add`. Never touch a widget from the worker.

**Request ids and cancel.** `_send` and `_cancel_request` bump `_request_id`. Every worker callback goes through `_run_if_current`, which drops it when its id is stale. Cancel cannot interrupt the worker, because it is blocked in a socket read that httpx cannot abort from another thread; the abandoned thread ends on its own (next token or read timeout) without touching the window. The worker gets its own `cancel_flag` as an argument rather than reading `self.cancel_flag`, which a retry has already replaced. It checks the flag between tokens, which is also how closing the window stops a stream.

**Snapshot per-request settings in `_send`.** The model, the system instruction, `thinking` and `auto_copy` (`self._current_auto_copy`) are read when the request starts, so editing a Gem mid-stream doesn't affect the reply in flight.

**Conversation rollback.** `_show_error`, `_cancel_request` and `_finish_stream` (on an empty reply) pop the trailing user turn off `self.history`, so a prompt without an answer doesn't poison the next turn's context.

**Retry and Cancel are always visible; only their sensitivity changes.** Cancel is active while a request is in flight. Retry is active after a failure, an empty reply or a cancel. Retry resends `_last_prompt` through `_send` with the Gem and model selected at click time, so switching away from an overloaded model first works. Only `_submit` clears the input buffer, so a draft typed after the failure survives a retry.

**The status row is the only sign a slow request is alive.** The API sends its response headers together with the first token, so a model that takes 20 s to start (measured 2026-10 on `gemini-3.5-flash-lite`) looks exactly like a stalled one on the wire. `stream_generate(..., on_status=cb)` reports `CONNECTING` and `WAITING` from an httpx `trace` extension (TCP connect started, request body sent) and `STREAMING` on the first text. That is what separates "can't reach Google" from "the model is slow". The trace extension needs `httpx.Client().stream(..., extensions=...)`; the top-level `httpx.stream` does not accept `extensions`. `on_status` runs on the worker thread, so `_worker` forwards it through `GLib.idle_add`. The connect timeout is `CONNECT_TIMEOUT` (10 s) so a dead network fails fast; the read timeout is `DEFAULT_TIMEOUT` (60 s of silence). Each `GeminiError.reason` is a short phrase for the status line ("model overloaded", "not on your plan", "rate limit reached, retry in 14h18m24s"); the full message goes to the response area.

**Per-Gem thinking is a fallback ladder.** The Gem's `thinking` bool maps to `generationConfig.thinkingConfig.thinkingLevel`. On tries `"high"`. Off tries `"minimal"`, then `"low"`. Both end with no `thinkingConfig` at all. A refused level comes back as HTTP 400 with "Thinking level ... is not supported", which `_stream_once` turns into `_UnsupportedThinkingLevel` so the loop moves to the next rung. Retrying is safe because the status check happens before any token is yielded. Measured 2026-09:

- `"minimal"` gives 0 thought tokens on the Flash-Lite line, 3.5-flash and 3.6-flash.
- 3.7-flash and 3.8-flash reject `"minimal"` and only go down to `"low"` (about 50-70 thought tokens).
- Gemma models reject `"low"` and return HTTP 500 on `"high"`. The 500 deliberately does not trigger a fallback, so real server errors stay visible.

`thinkingBudget` is not used: 3.x models reject `thinkingBudget: 0` with a generic "invalid argument" that has no thinking hint, so it cannot drive the ladder.

## Token usage

**Usage is counted locally because the API cannot report it.** `generativelanguage.googleapis.com` has no usage or quota method (checked against the full v1beta discovery document), and responses carry no `x-ratelimit-*` headers. A 429 names the exceeded quota (`QuotaFailure` violations plus `RetryInfo`) but never how much was used. Those names show the free tier's real meters: `generate_content_free_tier_requests` and `generate_content_free_tier_input_token_count`, per model, per minute and per day. Only input tokens are metered, which is why `usage.summary` puts the input count before the total. `totalTokenCount` (input + output + thinking) is the billing figure, not the quota figure. Cloud Monitoring and Service Usage hold the aggregate, but both reject API keys and need OAuth plus a project id. Don't look for a usage endpoint again.

How the counting works:

1. Every SSE chunk carries a cumulative `usageMetadata` for the reply so far, so `_stream_once` keeps only the newest one. Summing chunks would count the same tokens many times.
2. `stream_generate(..., on_usage=cb)` fires the callback once from a `finally`, on the worker thread, including on `GeneratorExit`. It must never touch a widget. `_worker` passes `usage_meta.update` and records the dict from its own `finally` through `GLib.idle_add`, outside the request-id check, because a canceled reply's tokens are billed anyway. When the window closes, the main loop quits before that idle callback runs, so a reply cut off by closing is not recorded.
3. The thinking ladder can call `_stream_once` several times, but a refused level fails before any chunk arrives, so the callback still fires once per reply.
4. `_record_usage` swallows `OSError`: an unwritable store must never break a reply.

## Clipboard

**Copy is two-tier.** `Ctrl+C` is handled at window level (`_copy_response_selection`) so a mouse selection in the read-only response view copies even while the input has focus. The window's key controller MUST use `Gtk.PropagationPhase.CAPTURE`: in BUBBLE, `input_view` consumes Ctrl+C with its empty selection first. If there is no response selection, the handler returns False so the input's native Ctrl+C runs. The per-Gem `auto_copy` flag copies the whole reply in `_finish_stream` and adds "(copied to clipboard)".

**Auto-paste must retry on Wayland.** Two per-Gem flags prefill `input_view` when the window opens, then select all so Enter sends it as is: `auto_paste_clipboard` reads CLIPBOARD (`get_clipboard()`, the last Ctrl+C) and `auto_paste_selection` reads PRIMARY (`get_primary_clipboard()`, text currently highlighted in any app). A freshly mapped Wayland window has not received the data offer at the first idle tick, so an immediate `read_text_async` fails with "No compatible transfer format found" or "Cannot read from empty clipboard". `_read_clipboard_into_input(sources, source_idx, attempt)` therefore retries every 50 ms up to `_AUTOPASTE_MAX_ATTEMPTS` (about 1 s). Don't collapse it to a single read; it would silently paste nothing. The callback bails when the buffer is not empty, so a late read never overwrites typed text. `sources` puts PRIMARY before CLIPBOARD, so with both flags on and nothing highlighted, the clipboard is used only after PRIMARY's full retry budget. PRIMARY holds only highlighted text from apps that support the selection protocol; Wayland gives no way to read unselected text.

## GNOME Shell extension

**Placement happens on the window manager's `map` signal, not `display::window-created`.** At creation a Wayland GTK window has no real frame size, and a `move_frame()` before mapping doesn't stick (the window lands top-left). The target monitor is captured at `window-created`, before the launcher takes focus. Matching is by app-id, so `APP_ID` in `main.py` and `TARGET_APP_ID` in `extension.js` must stay in sync.

**The two GNOME resource imports use different paths:**

```js
// extension.js, runs inside the gnome-shell process
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
// prefs.js, runs in a separate gjs process
import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
```

Prefs are hosted by `gjs -m /usr/share/gnome-shell/org.gnome.Shell.Extensions`, backed by `org.gnome.Shell.Extensions.src.gresource`; the lowercase `…/org/gnome/shell/…` tree only exists inside gnome-shell. A wrong path throws `ImportError: … The resource at "/org/gnome/shell/extensions/prefs.js" does not exist`, which Extension Manager and the Extensions app both show as a bare "Something's gone wrong". Check the real path instead of trusting memory:

```bash
gresource list /usr/share/gnome-shell/org.gnome.Shell.Extensions.src.gresource | grep prefs
journalctl --user -b --grep "JS ERROR"   # where the swallowed error lands
```

**Only `extension.js` and `metadata.json` need a logout.** The prefs process starts fresh for each dialog and reads `prefs.js` from disk, so re-running `install.sh` and reopening prefs is enough. GNOME Shell on Wayland can't reload in place, so extension changes need a log out and in. The shell refuses a second dialog with "Already showing a prefs dialog"; close the stale one (or kill its gjs pid) first.

## Config and secrets

- `~/.config/gemini-gem-shortcut/config.json` (mode 0600) holds the API key in plaintext. Moving it to GNOME Keyring via `libsecret` is planned but not started.
- `.gitignore` excludes a root-level `config.json` so a stray copy can't be committed.

## Updating the model list

Model IDs live in two places; change both: `DEFAULT_CONFIG` in `config.py` (the source of truth) and the config example in `README.md`.

**Changing the defaults does not migrate an existing config.** `config.load()` fills only missing top-level keys with `setdefault`, so an existing `models` list is kept. Rewrite the live `~/.config/gemini-gem-shortcut/config.json` separately, through settings or a one-off `config.load()`, overwrite `models`, `config.save()` (which keeps the key, the Gems and mode 0600). Also check each Gem's `default_model` for IDs that no longer exist.

**Verify against the API, not docs or memory.** `GET …/v1beta/models?key=$KEY` lists what the key can address. Then stream one token through `gemini_client.stream_generate` for each ID, because being listed doesn't mean it works:

- Every `*-pro*` ID returns `HTTP 429 … limit: 0` on a free key. `limit: 0` is a hard zero allowance, not throttling, and retrying never helps. Keeping a Pro entry is deliberate: it works once billing is enabled.
- Unversioned aliases (`gemini-flash-latest`, `gemini-pro-latest`) float to the newest model in their tier. Prefer pinned IDs so an upstream swap can't change behavior silently.
- Some models share a daily quota: on 2026-10-20 a 429 from `gemini-3.7-flash` named the 20 requests/day limit of `gemini-3.8-flash`.

## Commit and push

- Never add `Co-Authored-By` or any AI attribution to commits.
- Repo: `git@github.com:iboalali/Gemini-Gem-Shortcut.git`, default branch `main`.
